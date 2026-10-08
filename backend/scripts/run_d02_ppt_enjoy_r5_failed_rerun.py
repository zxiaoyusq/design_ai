"""仅重跑上一批失败的用研图片；五路 GPT-6 Sol medium，每图不自动重试。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import sys
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.prism_dna_sol_r5 import PRIMARY_PROMPT_PATH, PROMPT_VERSION, SKILL_ROOT
from app.services.dna.prism_r5 import RESULT_DIR, _safe_exception, run_prism_r5_extraction
from app.services.dna.storage import _atomic_write


SOURCE_BATCH_ID = "ppt_enjoy_20260930_gpt6sol_r5_medium"
BATCH_ID = SOURCE_BATCH_ID + "_failed_rerun1"
MODEL_ID = "gpt-6-sol"
REASONING_EFFORT = "medium"
MAX_WORKERS = 5
RESEARCH_ROOT = PROJECT_ROOT / "data" / "userreseach_data"
SOURCE_JSON = RESEARCH_ROOT / "users_selected_5.json"
BATCH_ROOT = RESEARCH_ROOT / "liked_images_d02_results" / "batches"
SOURCE_MANIFEST = BATCH_ROOT / SOURCE_BATCH_ID / "manifest.json"
BATCH_DIR = BATCH_ROOT / BATCH_ID
MANIFEST_PATH = BATCH_DIR / "manifest.json"
FAILURES_PATH = BATCH_DIR / "failures.json"
TRACE_ID = re.compile(r"运行记录 ([a-f0-9]{32})")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _counts(manifest: dict[str, Any]) -> dict[str, int]:
    return {state: sum(row["status"] == state for row in manifest["entries"])
            for state in ("pending", "running", "completed", "partial", "failed")}


def _save(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    manifest["counts"] = _counts(manifest)
    _write_json(MANIFEST_PATH, manifest)
    _write_json(FAILURES_PATH, {
        "batch_id": BATCH_ID,
        "failed_count": manifest["counts"]["failed"],
        "partial_count": manifest["counts"]["partial"],
        "entries": [{key: row.get(key) for key in
                     ("source_path", "sha256", "status", "result_id", "error", "trace_id", "started_at", "finished_at")}
                    for row in manifest["entries"] if row["status"] in {"failed", "partial"}],
    })


def _source_entries() -> tuple[list[dict[str, Any]], str]:
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    if source.get("batch_id") != SOURCE_BATCH_ID or source.get("counts", {}).get("failed") != 95:
        raise ValueError("来源批次或失败数量已变化，拒绝改变重跑范围")
    if source["source_json_sha256"] != _sha(SOURCE_JSON):
        raise ValueError("用研 JSON 已变化，拒绝重跑")
    if source["skill_sha256"] != _sha(SKILL_ROOT / "SKILL.md") or source["prompt_sha256"] != _sha(PRIMARY_PROMPT_PATH):
        raise ValueError("冻结 Skill 或 Prompt 已变化，拒绝混用版本")
    entries = []
    for row in source["entries"]:
        if row["status"] != "failed":
            continue
        relative = PurePosixPath(row["source_path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "ppt_images":
            raise ValueError(f"不安全的用研图片路径：{relative}")
        path = RESEARCH_ROOT / relative
        if not path.resolve().is_relative_to(RESEARCH_ROOT.resolve()) or not path.is_file() or _sha(path) != row["sha256"]:
            raise ValueError(f"图片缺失、越界或内容变化：{relative}")
        entries.append({
            "source_path": row["source_path"], "sha256": row["sha256"],
            "content_type": row["content_type"], "size": row["size"],
            "preferences": row["preferences"], "source_trace_id": row.get("trace_id"),
            "source_error": row.get("error"), "status": "pending", "result_id": None,
            "trace_id": None, "error": None, "started_at": None, "finished_at": None,
            "duration_seconds": None, "model_attempts": 0,
        })
    if len(entries) != 95:
        raise ValueError(f"来源失败路径应为 95 条，实际 {len(entries)}")
    return entries, source["input_fingerprint"]


def prepare() -> dict[str, Any]:
    entries, source_fingerprint = _source_entries()
    fingerprint = hashlib.sha256(json.dumps(
        [(row["source_path"], row["sha256"]) for row in entries],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if any((manifest.get("input_fingerprint") != fingerprint,
                manifest.get("source_input_fingerprint") != source_fingerprint,
                manifest.get("model_id") != MODEL_ID,
                manifest.get("reasoning_effort") != REASONING_EFFORT,
                manifest.get("skill_sha256") != _sha(SKILL_ROOT / "SKILL.md"),
                manifest.get("prompt_sha256") != _sha(PRIMARY_PROMPT_PATH),
                manifest.get("max_concurrency") != MAX_WORKERS)):
            raise ValueError("已有重跑批次的输入或配置不同，拒绝复用")
        return manifest
    manifest = {
        "batch_id": BATCH_ID, "status": "prepared", "model_id": MODEL_ID,
        "reasoning_effort": REASONING_EFFORT, "max_concurrency": MAX_WORKERS,
        "automatic_retries": False, "source_batch_id": SOURCE_BATCH_ID,
        "source_manifest": str(SOURCE_MANIFEST.relative_to(PROJECT_ROOT)),
        "source_input_fingerprint": source_fingerprint,
        "source_json": str(SOURCE_JSON.relative_to(PROJECT_ROOT)),
        "source_json_sha256": _sha(SOURCE_JSON), "input_fingerprint": fingerprint,
        "selection_rule": "仅来源批次 status=failed 的 95 条路径；按 SHA256 去重调用，不含 partial",
        "total_paths": len(entries), "unique_image_sha256": len({row["sha256"] for row in entries}),
        "skill_sha256": _sha(SKILL_ROOT / "SKILL.md"),
        "prompt_sha256": _sha(PRIMARY_PROMPT_PATH), "prompt_version": PROMPT_VERSION,
        "result_directory": str(RESULT_DIR.relative_to(PROJECT_ROOT)),
        "created_at": _now(), "updated_at": _now(), "stopped_reason": None,
        "entries": entries,
    }
    _save(manifest)
    return manifest


def _run_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    started = monotonic()
    try:
        for row in group:
            if _sha(RESEARCH_ROOT / row["source_path"]) != row["sha256"]:
                raise ValueError(f"执行前图片内容发生变化：{row['source_path']}")
        source_record = {
            "batch_id": BATCH_ID, "rerun_of_batch_id": SOURCE_BATCH_ID,
            "source_path": group[0]["source_path"],
            "source_paths": [row["source_path"] for row in group],
            "source_trace_ids": [row["source_trace_id"] for row in group],
            "source_json": str(SOURCE_JSON.relative_to(PROJECT_ROOT)),
            "source_json_sha256": _sha(SOURCE_JSON),
            "preferences": [pref for row in group for pref in row["preferences"]],
        }
        output = run_prism_r5_extraction(
            image_path=RESEARCH_ROOT / group[0]["source_path"],
            content_type=group[0]["content_type"], model_id=MODEL_ID,
            reasoning_effort=REASONING_EFFORT, user_prompt="", source_record=source_record,
        )
        result = json.loads((RESULT_DIR / f"{output.result_id}.json").read_text(encoding="utf-8"))
        focus_complete = result["validation"]["focus_complete"]
        return {
            "status": "completed" if focus_complete else "partial",
            "result_id": output.result_id, "trace_id": output.result_id,
            "error": None if focus_complete else "困难项复核未完成：" + str(result["execution"].get("focus_error") or "原因未记录"),
            "duration_seconds": round(monotonic() - started, 3),
        }
    except Exception as exc:
        message = _safe_exception(exc)
        match = TRACE_ID.search(message)
        return {"status": "failed", "result_id": None,
                "trace_id": match.group(1) if match else None,
                "error": message, "duration_seconds": round(monotonic() - started, 3)}


def _recover_running(manifest: dict[str, Any]) -> None:
    """进程中断时只接纳已落盘结果；未落盘任务记失败，不隐式重试。"""
    if not any(row["status"] == "running" for row in manifest["entries"]):
        return
    saved = {}
    for path in RESULT_DIR.glob("*.json"):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            if (result.get("source", {}).get("research") or {}).get("batch_id") == BATCH_ID:
                saved[result["source"]["image_sha256"]] = result
        except (OSError, ValueError, KeyError):
            continue
    for row in manifest["entries"]:
        if row["status"] == "running":
            result = saved.get(row["sha256"])
            row.update(
                status=("completed" if result["validation"]["focus_complete"] else "partial") if result else "failed",
                result_id=result["id"] if result else None,
                trace_id=result["id"] if result else row["trace_id"],
                error=None if result and result["validation"]["focus_complete"] else
                ("困难项复核未完成" if result else "执行进程中断；结果未落盘，按不重试规则记录失败"),
                finished_at=_now(),
            )


def execute() -> dict[str, Any]:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    with (BATCH_DIR / "run.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = prepare()
        if manifest["status"] == "blocked":
            raise ValueError("批次已因额度或鉴权问题停止，不会自动继续")
        _recover_running(manifest)
        _save(manifest)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in manifest["entries"]:
            if row["status"] == "pending":
                groups[row["sha256"]].append(row)
        if not groups:
            manifest["status"] = "partial" if manifest["counts"]["failed"] or manifest["counts"]["partial"] else "completed"
            _save(manifest)
            return manifest
        manifest["status"] = "running"
        _save(manifest)
        pending = iter(groups.values())
        active = {}
        stopped_reason = None
        with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="d02-r5-rerun") as pool:
            def submit_next() -> bool:
                try:
                    group = next(pending)
                except StopIteration:
                    return False
                for row in group:
                    row.update(status="running", started_at=_now())
                _save(manifest)
                active[pool.submit(_run_group, group)] = group
                return True

            for _ in range(MAX_WORKERS):
                if not submit_next():
                    break
            while active:
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    group = active.pop(future)
                    outcome = future.result()
                    for index, row in enumerate(group):
                        row.update(outcome, finished_at=_now(), model_attempts=1 if index == 0 else 0)
                    # 只根据明确状态码/额度词停批，不能把 trace ID 中的数字当作 403。
                    error = (outcome["error"] or "").lower()
                    if ("quota exceeded" in error or "insufficient_quota" in error
                            or "unauthorized" in error or "invalid api key" in error
                            or re.search(r"(?:error code|status code|http status)\s*[:=]?\s*403\b", error)):
                        stopped_reason = "model_quota_or_auth_error"
                    _save(manifest)
                    print(f"{_now()} {outcome['status']} {group[0]['source_path']} "
                          f"completed={manifest['counts']['completed']} failed={manifest['counts']['failed']} "
                          f"pending={manifest['counts']['pending']}", flush=True)
                    if stopped_reason is None:
                        submit_next()
        manifest["stopped_reason"] = stopped_reason
        manifest["status"] = "blocked" if stopped_reason else (
            "partial" if manifest["counts"]["failed"] or manifest["counts"]["partial"] else "completed")
        _save(manifest)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "run", "status"))
    command = parser.parse_args().command
    manifest = prepare() if command == "prepare" else execute() if command == "run" else json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(json.dumps({"batch_id": BATCH_ID, "status": manifest["status"],
                      "counts": _counts(manifest), "stopped_reason": manifest["stopped_reason"]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

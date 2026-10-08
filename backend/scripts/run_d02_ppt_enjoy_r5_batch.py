"""按旧版冻结用研清单以五路 GPT-6 Sol medium 执行 Sol R5，不重试失败图片。"""

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


BATCH_ID = "ppt_enjoy_20260930_gpt6sol_r5_medium"
MODEL_ID = "gpt-6-sol"
REASONING_EFFORT = "medium"
MAX_WORKERS = 5
RESEARCH_ROOT = PROJECT_ROOT / "data" / "userreseach_data"
SOURCE_JSON = RESEARCH_ROOT / "users_selected_5.json"
OLD_MANIFEST = RESEARCH_ROOT / "liked_images_d02_results" / "batches" / "ppt_enjoy_20260928_gemini38" / "manifest.json"
BATCH_DIR = RESEARCH_ROOT / "liked_images_d02_results" / "batches" / BATCH_ID
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
    return {
        state: sum(entry["status"] == state for entry in manifest["entries"])
        for state in ("pending", "running", "completed", "partial", "failed")
    }


def _quota_or_auth_error(error: str | None) -> bool:
    """只识别明确的额度／鉴权响应，不把追踪 ID 中碰巧出现的 403 当状态码。"""

    message = (error or "").lower()
    return (
        "quota exceeded" in message
        or "insufficient_quota" in message
        or "unauthorized" in message
        or "invalid api key" in message
        or re.search(r"(?:error code|status code|http status)\s*[:=]?\s*403\b", message) is not None
    )


def _save(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    manifest["counts"] = _counts(manifest)
    _write_json(MANIFEST_PATH, manifest)
    _write_json(FAILURES_PATH, {
        "batch_id": BATCH_ID,
        "failed_count": manifest["counts"]["failed"],
        "partial_count": manifest["counts"]["partial"],
        "entries": [
            {key: entry.get(key) for key in (
                "source_path", "sha256", "status", "result_id", "error", "trace_id", "started_at", "finished_at"
            )}
            for entry in manifest["entries"] if entry["status"] in {"failed", "partial"}
        ],
    })


def _source_entries() -> list[dict[str, Any]]:
    old = json.loads(OLD_MANIFEST.read_text(encoding="utf-8"))
    if old["total_paths"] != 551 or old["source_json_sha256"] != _sha(SOURCE_JSON):
        raise ValueError("旧版冻结清单或用研 JSON 已变化，拒绝扩大或改变图片范围")
    entries = []
    for row in old["entries"]:
        relative = PurePosixPath(row["source_path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "ppt_images":
            raise ValueError(f"不安全的用研图片路径：{relative}")
        path = RESEARCH_ROOT / relative
        if not path.resolve().is_relative_to(RESEARCH_ROOT.resolve()):
            raise ValueError(f"用研图片实际路径越出目录：{relative}")
        if not path.is_file() or _sha(path) != row["sha256"]:
            raise ValueError(f"图片缺失或内容与冻结清单不同：{relative}")
        entries.append({
            "source_path": row["source_path"], "sha256": row["sha256"],
            "content_type": row["content_type"], "size": row["size"],
            "preferences": row["preferences"], "status": "pending",
            "result_id": None, "trace_id": None, "error": None,
            "started_at": None, "finished_at": None, "duration_seconds": None,
            "model_attempts": 0,
        })
    if len(entries) != 551:
        raise ValueError(f"冻结清单应为 551 条路径，实际 {len(entries)}")
    return entries


def prepare() -> dict[str, Any]:
    entries = _source_entries()
    input_fingerprint = hashlib.sha256(json.dumps(
        [(row["source_path"], row["sha256"]) for row in entries],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if any((
            manifest.get("input_fingerprint") != input_fingerprint,
            manifest.get("model_id") != MODEL_ID,
            manifest.get("reasoning_effort") != REASONING_EFFORT,
            manifest.get("skill_sha256") != _sha(SKILL_ROOT / "SKILL.md"),
            manifest.get("prompt_sha256") != _sha(PRIMARY_PROMPT_PATH),
            manifest.get("max_concurrency") != MAX_WORKERS,
        )):
            raise ValueError("已有新批次的输入、Skill 或模型配置不同，拒绝复用")
        return manifest
    manifest = {
        "batch_id": BATCH_ID, "status": "prepared", "model_id": MODEL_ID,
        "reasoning_effort": REASONING_EFFORT, "max_concurrency": MAX_WORKERS,
        "automatic_retries": False, "preflight_size": 5,
        "source_json": str(SOURCE_JSON.relative_to(PROJECT_ROOT)),
        "source_json_sha256": _sha(SOURCE_JSON),
        "source_manifest": str(OLD_MANIFEST.relative_to(PROJECT_ROOT)),
        "input_fingerprint": input_fingerprint,
        "selection_rule": "冻结 R17 批次的 551 条 ENJOY PPT 图片路径；按 SHA256 去重调用",
        "total_paths": len(entries), "unique_image_sha256": len({row["sha256"] for row in entries}),
        "skill_sha256": _sha(SKILL_ROOT / "SKILL.md"),
        "prompt_sha256": _sha(PRIMARY_PROMPT_PATH), "prompt_version": PROMPT_VERSION,
        "result_directory": str(RESULT_DIR.relative_to(PROJECT_ROOT)),
        "created_at": _now(), "updated_at": _now(), "stopped_reason": None,
        "entries": entries,
    }
    _save(manifest)
    return manifest


def _source_record(group: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "batch_id": BATCH_ID,
        "source_path": group[0]["source_path"],
        "source_paths": [entry["source_path"] for entry in group],
        "source_json": str(SOURCE_JSON.relative_to(PROJECT_ROOT)),
        "source_json_sha256": _sha(SOURCE_JSON),
        "preferences": [preference for entry in group for preference in entry["preferences"]],
    }


def _recover_running(manifest: dict[str, Any]) -> None:
    """中断后只认已落盘成功结果；其余在途图片记录失败，不隐式重发。"""

    running = {entry["sha256"] for entry in manifest["entries"] if entry["status"] == "running"}
    if not running:
        return
    saved: dict[str, str] = {}
    for path in RESULT_DIR.glob("*.json"):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (result.get("source", {}).get("research") or {}).get("batch_id") == BATCH_ID:
            saved[result["source"]["image_sha256"]] = result["id"]
    for entry in manifest["entries"]:
        if entry["status"] != "running":
            continue
        result_id = saved.get(entry["sha256"])
        entry.update(
            status="completed" if result_id else "failed",
            result_id=result_id,
            error=None if result_id else "执行进程中断；结果未落盘，按不重试规则记录失败",
            finished_at=_now(),
        )


def _reconcile_partial_results(manifest: dict[str, Any]) -> None:
    """主提取可用但定点复核失败时保留结果，单列为部分完成。"""

    for entry in manifest["entries"]:
        if entry["status"] != "completed" or not entry["result_id"]:
            continue
        path = RESULT_DIR / f"{entry['result_id']}.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        if not result["validation"]["focus_complete"]:
            entry.update(
                status="partial",
                error="困难项复核未完成：" + str(result["execution"].get("focus_error") or "原因未记录"),
            )


def _run_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    started = monotonic()
    path = RESEARCH_ROOT / group[0]["source_path"]
    try:
        for entry in group:
            if _sha(RESEARCH_ROOT / entry["source_path"]) != entry["sha256"]:
                raise ValueError(f"图片内容在执行前发生变化：{entry['source_path']}")
        output = run_prism_r5_extraction(
            image_path=path, content_type=group[0]["content_type"], model_id=MODEL_ID,
            reasoning_effort=REASONING_EFFORT, user_prompt="",
            source_record=_source_record(group),
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
                "trace_id": match.group(1) if match else None, "error": message,
                "duration_seconds": round(monotonic() - started, 3)}


def execute(*, preflight_only: bool) -> dict[str, Any]:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    with (BATCH_DIR / "run.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = prepare()
        if manifest["status"] == "blocked":
            if (
                manifest["stopped_reason"] == "model_quota_or_auth_error"
                and not any(_quota_or_auth_error(entry["error"]) for entry in manifest["entries"] if entry["status"] in {"failed", "partial"})
            ):
                # 旧判定曾匹配追踪 ID 中的 403；只恢复未提交项，不重发失败图片。
                manifest.setdefault("stop_history", []).append({
                    "at": _now(), "reason": "trace_id_403_false_positive",
                    "completed_count": manifest["counts"]["completed"],
                    "failed_count": manifest["counts"]["failed"],
                })
                manifest["status"] = "partial"
                manifest["stopped_reason"] = None
                _save(manifest)
            else:
                raise ValueError("批次已因系统性错误停止；不会自动继续或重试")
        _recover_running(manifest)
        _reconcile_partial_results(manifest)
        _save(manifest)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in manifest["entries"]:
            if entry["status"] == "pending":
                groups[entry["sha256"]].append(entry)
        selected = list(groups.values())[:5] if preflight_only else list(groups.values())
        if not selected:
            manifest["status"] = "partial" if manifest["counts"]["failed"] or manifest["counts"]["partial"] else "completed"
            _save(manifest)
            return manifest
        manifest["status"] = "preflight_running" if preflight_only else "running"
        _save(manifest)
        active: dict[Any, list[dict[str, Any]]] = {}
        pending = iter(selected)
        stopped_reason: str | None = None
        success_in_this_run = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="d02-r5-medium") as pool:
            def submit_next() -> bool:
                try:
                    group = next(pending)
                except StopIteration:
                    return False
                for entry in group:
                    entry.update(status="running", started_at=_now())
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
                    if outcome["status"] in {"completed", "partial"}:
                        success_in_this_run += 1
                    for index, entry in enumerate(group):
                        entry.update(outcome, finished_at=_now(), model_attempts=1 if index == 0 else 0)
                    if _quota_or_auth_error(outcome["error"]):
                        stopped_reason = "model_quota_or_auth_error"
                    _save(manifest)
                    print(f"{_now()} {outcome['status']} {group[0]['source_path']} "
                          f"completed={manifest['counts']['completed']} failed={manifest['counts']['failed']} "
                          f"pending={manifest['counts']['pending']}", flush=True)
                    if stopped_reason is None:
                        submit_next()

        if preflight_only and success_in_this_run == 0:
            stopped_reason = stopped_reason or "five_way_preflight_no_success"
        manifest["stopped_reason"] = stopped_reason
        manifest["status"] = (
            "blocked" if stopped_reason else
            "preflight_complete" if preflight_only and manifest["counts"]["pending"] else
            "partial" if manifest["counts"]["failed"] or manifest["counts"]["partial"] else "completed"
        )
        _save(manifest)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "preflight", "run", "status"))
    args = parser.parse_args()
    if args.command == "prepare":
        manifest = prepare()
    elif args.command == "preflight":
        manifest = execute(preflight_only=True)
    elif args.command == "run":
        manifest = execute(preflight_only=False)
    else:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(json.dumps({
        "batch_id": BATCH_ID, "status": manifest["status"],
        "model_id": MODEL_ID, "reasoning_effort": REASONING_EFFORT,
        "counts": _counts(manifest), "stopped_reason": manifest["stopped_reason"],
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

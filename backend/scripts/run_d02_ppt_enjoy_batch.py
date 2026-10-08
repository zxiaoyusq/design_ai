"""按用研 ENJOY 引用冻结 551 张 PPT 图片，最多五路执行 D02 候选提取。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import mimetypes
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

from app.agents.prism_image_dna import PROMPT_PATH, PROMPT_VERSION, SKILL_ROOT
from app.services.dna.prism_v2 import (
    LIKED_IMAGES_RESULT_DIR,
    list_prism_results,
    load_prism_result,
    reuse_prism_result,
    run_prism_v2_extraction,
)
from app.services.dna.storage import _atomic_write


MODEL_ID = "gemini-3.8-flash"
BATCH_ID = "ppt_enjoy_20260928_gemini38"
RESEARCH_ROOT = PROJECT_ROOT / "data" / "userreseach_data"
SOURCE_JSON = RESEARCH_ROOT / "users_selected_5.json"
BATCH_DIR = LIKED_IMAGES_RESULT_DIR / "batches" / BATCH_ID
MANIFEST_PATH = BATCH_DIR / "manifest.json"
MAX_WORKERS = 5


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = _now()
    _atomic_write(
        MANIFEST_PATH,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _research_entries() -> list[dict[str, Any]]:
    """仅按明确 ENJOY 的直接本地图引用选图，保留多处偏好证据。"""

    data = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for user in data["users"]:
        for preference in user.get("image_preferences", []):
            raw = preference.get("local_path")
            if str(preference.get("emotion_tag") or "").strip().upper() != "ENJOY":
                continue
            if not isinstance(raw, str) or not raw.startswith("ppt_images/"):
                continue
            relative = PurePosixPath(raw)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"不安全的图片路径：{raw}")
            by_path[raw].append({
                "user_id": user["id"], "user_name": user["name"],
                "preference_image_id": preference.get("image_id"),
                "emotion_tag": "ENJOY", "ref_pic_code": preference.get("ref_pic_code"),
                "source_file": preference.get("source_file"),
                "source_slide": preference.get("source_slide"),
                "source_id": preference.get("source_id"),
            })
    entries = []
    for relative_path, preferences in sorted(by_path.items()):
        path = RESEARCH_ROOT / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"ENJOY 引用图片缺失：{relative_path}")
        content_type = mimetypes.guess_type(path.name)[0]
        if content_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError(f"不支持的图片格式：{relative_path}")
        entries.append({
            "source_path": relative_path,
            "sha256": _sha(path), "size": path.stat().st_size,
            "content_type": content_type, "preferences": preferences,
            "status": "pending", "result_id": None, "error": None,
            "started_at": None, "finished_at": None, "duration_seconds": None,
            "model_attempts": 0, "reused_from_result_id": None,
        })
    return entries


def prepare() -> dict[str, Any]:
    entries = _research_entries()
    if len(entries) != 551:
        raise ValueError(f"ENJOY 唯一路径应为 551 张，实际 {len(entries)} 张；停止以免扩大范围")
    if MANIFEST_PATH.exists():
        existing = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if (
            existing.get("source_json_sha256") != _sha(SOURCE_JSON)
            or [(row["source_path"], row["sha256"]) for row in existing["entries"]]
            != [(row["source_path"], row["sha256"]) for row in entries]
        ):
            raise ValueError("已有批次的输入快照与当前用研文件不一致，拒绝覆盖")
        return existing
    manifest = {
        "batch_id": BATCH_ID, "status": "prepared", "model_id": MODEL_ID,
        "source_json": str(SOURCE_JSON.relative_to(PROJECT_ROOT)),
        "source_json_sha256": _sha(SOURCE_JSON),
        "skill_sha256": _sha(SKILL_ROOT / "SKILL.md"),
        "prompt_sha256": _sha(PROMPT_PATH), "prompt_version": PROMPT_VERSION,
        "selection_rule": "image_preferences.emotion_tag=ENJOY 且 local_path 位于 ppt_images/，按路径去重",
        "total_paths": len(entries), "unique_image_sha256": len({row["sha256"] for row in entries}),
        "max_concurrency": MAX_WORKERS, "created_at": _now(), "updated_at": _now(),
        "entries": entries,
    }
    _write_manifest(manifest)
    return manifest


def _source_record(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": BATCH_ID, "source_path": entry["source_path"],
        "source_json": str(SOURCE_JSON.relative_to(PROJECT_ROOT)),
        "source_json_sha256": _sha(SOURCE_JSON),
        "preferences": entry["preferences"],
    }


def _existing_result_ids(manifest: dict[str, Any]) -> dict[str, str]:
    """进程中断后从已保存结果恢复，避免重复调用同一原图。"""

    matches: dict[str, str] = {}
    for item in list_prism_results():
        research = item.get("research") or {}
        if research.get("batch_id") != BATCH_ID:
            continue
        try:
            result = load_prism_result(item["id"])
        except (OSError, ValueError):
            continue
        if (
            result["execution"].get("model_id") == MODEL_ID
            and result["execution"].get("prompt_sha256") == manifest["prompt_sha256"]
            and result["source"].get("image_sha256")
        ):
            matches[research["source_path"]] = item["id"]
    return matches


def _run_group(group: list[dict[str, Any]], existing_id: str | None) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    primary_id = existing_id
    for entry in group:
        started = monotonic()
        path = RESEARCH_ROOT / entry["source_path"]
        try:
            if _sha(path) != entry["sha256"]:
                raise ValueError("图片内容哈希变化，拒绝使用冻结清单以外的内容")
            if primary_id is None:
                output = run_prism_v2_extraction(
                    image_path=path, content_type=entry["content_type"], model_id=MODEL_ID,
                    user_prompt="", source_record=_source_record(entry),
                )
                primary_id = output.result_id
                model_attempts = 1
                reused_from = None
            else:
                output = reuse_prism_result(
                    primary_id, image_path=path, source_record=_source_record(entry)
                )
                model_attempts = 0
                reused_from = primary_id
            outcomes.append({
                "source_path": entry["source_path"], "status": "completed",
                "result_id": output.result_id, "error": None,
                "duration_seconds": round(monotonic() - started, 3),
                "model_attempts": model_attempts,
                "reused_from_result_id": reused_from,
            })
        except Exception as exc:  # 每张图片的真实失败和用时均写入清单。
            outcomes.append({
                "source_path": entry["source_path"], "status": "failed",
                "result_id": None, "error": f"{type(exc).__name__}: {exc}",
                "duration_seconds": round(monotonic() - started, 3),
                "model_attempts": 1 if primary_id is None else 0,
                "reused_from_result_id": None,
            })
            if primary_id is None:
                # 同哈希的另一条引用不重复付费调用，复用同一失败记录。
                for other in group[len(outcomes):]:
                    outcomes.append({
                        "source_path": other["source_path"], "status": "failed",
                        "result_id": None, "error": f"同原图提取失败：{type(exc).__name__}: {exc}",
                        "duration_seconds": 0, "model_attempts": 0,
                        "reused_from_result_id": None,
                    })
                break
    return outcomes


def run() -> dict[str, Any]:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    with (BATCH_DIR / "run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = prepare()
        if manifest["model_id"] != MODEL_ID or manifest["prompt_sha256"] != _sha(PROMPT_PATH):
            raise ValueError("模型或提示版本与冻结批次不同")
        by_path = {entry["source_path"]: entry for entry in manifest["entries"]}
        existing = _existing_result_ids(manifest)
        for entry in manifest["entries"]:
            result_id = existing.get(entry["source_path"])
            if result_id and entry["status"] != "completed":
                entry.update(status="completed", result_id=result_id, error=None, finished_at=_now())
            elif entry["status"] == "running":
                entry["status"] = "pending"
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in manifest["entries"]:
            if entry["status"] == "pending":
                groups[entry["sha256"]].append(entry)
        pending_groups = iter(groups.values())
        manifest["status"] = "running"
        _write_manifest(manifest)
        stopped_reason = None
        with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="d02-ppt-enjoy") as executor:
            active = {}

            def submit_next() -> bool:
                try:
                    group = next(pending_groups)
                except StopIteration:
                    return False
                base_id = next((existing[e["source_path"]] for e in group if e["source_path"] in existing), None)
                for entry in group:
                    entry["status"] = "running"
                    entry["started_at"] = _now()
                _write_manifest(manifest)
                active[executor.submit(_run_group, group, base_id)] = group
                return True

            for _ in range(MAX_WORKERS):
                if not submit_next():
                    break
            while active:
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    group = active.pop(future)
                    try:
                        outcomes = future.result()
                    except Exception as exc:
                        outcomes = [{
                            "source_path": e["source_path"], "status": "failed", "result_id": None,
                            "error": f"批次执行异常：{type(exc).__name__}: {exc}",
                            "duration_seconds": None, "model_attempts": 0,
                            "reused_from_result_id": None,
                        } for e in group]
                    for outcome in outcomes:
                        entry = by_path[outcome.pop("source_path")]
                        entry.update(outcome, finished_at=_now())
                        if outcome["status"] == "failed" and any(
                            token in (outcome["error"] or "").lower()
                            for token in ("quota", "403", "unauthorized", "invalid api key")
                        ):
                            stopped_reason = "model_quota_or_auth_error"
                    completed = sum(row["status"] == "completed" for row in manifest["entries"])
                    failed = sum(row["status"] == "failed" for row in manifest["entries"])
                    manifest["completed_count"] = completed
                    manifest["failed_count"] = failed
                    manifest["pending_count"] = len(manifest["entries"]) - completed - failed
                    _write_manifest(manifest)
                    print(f"{_now()} completed={completed} failed={failed} pending={manifest['pending_count']}", flush=True)
                    if stopped_reason is None:
                        submit_next()
        manifest["status"] = (
            "blocked" if stopped_reason else "partial" if any(e["status"] == "failed" for e in manifest["entries"])
            else "completed"
        )
        manifest["stopped_reason"] = stopped_reason
        _write_manifest(manifest)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "run", "status"])
    args = parser.parse_args()
    if args.command == "prepare":
        manifest = prepare()
    elif args.command == "run":
        manifest = run()
    else:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    counts = {status: sum(e["status"] == status for e in manifest["entries"]) for status in ("pending", "running", "completed", "failed")}
    print(json.dumps({"batch_id": BATCH_ID, "status": manifest["status"], "counts": counts}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

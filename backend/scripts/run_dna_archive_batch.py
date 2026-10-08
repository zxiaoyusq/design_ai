"""从图片 ZIP 执行可追溯的并行设计 DNA 批量提取。"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import shutil
import sys
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Lock
from time import perf_counter
from typing import Any
from zipfile import BadZipFile, ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.dna.extraction import ExtractionOutput, run_design_dna_extraction
from app.services.dna.storage import RESULTS_DIR

SUPPORTED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})


@dataclass(frozen=True, slots=True)
class ArchiveImage:
    """ZIP 内通过路径和格式校验的一张待提取图片。"""

    archive_path: str
    member_name: str
    extracted_path: str
    sha256: str


class ArchiveBatchError(RuntimeError):
    """压缩包输入或批处理运行状态不满足安全约束。"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json_write(path: Path, data: Any) -> None:
    """原子保存运行清单，进程中断时仍保留已完成图片的记录。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _safe_image_members(archive_path: Path) -> list[str]:
    """仅接受 ZIP 根下 `images/` 的普通图片，并拒绝路径穿越。"""

    try:
        with ZipFile(archive_path) as archive:
            members: list[str] = []
            for info in archive.infolist():
                member_path = PurePosixPath(info.filename)
                if info.is_dir():
                    continue
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ArchiveBatchError(
                        f"压缩包包含不安全路径：{archive_path.name}:{info.filename}"
                    )
                if (
                    len(member_path.parts) != 2
                    or member_path.parts[0] != "images"
                    or member_path.suffix.lower() not in SUPPORTED_EXTENSIONS
                ):
                    continue
                members.append(info.filename)
    except BadZipFile as exc:
        raise ArchiveBatchError(f"压缩包不可读取：{archive_path}") from exc
    if not members:
        raise ArchiveBatchError(f"压缩包没有可提取图片：{archive_path}")
    return sorted(members)


def extract_archives(archive_paths: list[Path], images_dir: Path) -> list[ArchiveImage]:
    """安全解压图片；同名文件必须有完全相同的内容才能复用。"""

    images_dir.mkdir(parents=True, exist_ok=True)
    images: list[ArchiveImage] = []
    seen_names: dict[str, str] = {}
    for archive_path in archive_paths:
        for member_name in _safe_image_members(archive_path):
            target = images_dir / PurePosixPath(member_name).name
            if target.name != PurePosixPath(member_name).name:
                raise ArchiveBatchError(f"图片文件名不安全：{member_name}")
            with ZipFile(archive_path) as archive:
                payload = archive.read(member_name)
            digest = hashlib.sha256(payload).hexdigest()
            prior_digest = seen_names.get(target.name)
            if prior_digest is not None:
                if prior_digest != digest:
                    raise ArchiveBatchError(
                        f"两个压缩包存在同名但内容不同的图片：{target.name}"
                    )
                continue
            seen_names[target.name] = digest
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ArchiveBatchError(f"目标目录已存在冲突图片：{target}")
            else:
                target.write_bytes(payload)
            images.append(
                ArchiveImage(
                    archive_path=str(archive_path.relative_to(PROJECT_ROOT)),
                    member_name=member_name,
                    extracted_path=str(target.relative_to(PROJECT_ROOT)),
                    sha256=digest,
                )
            )
    return images


def _successful_result_hashes() -> set[str]:
    """只有追溯记录及页面/完整结果均存在，才视为图片已有成功提取。"""

    hashes: set[str] = set()
    for trace_path in (RESULTS_DIR / ".metadata").glob("*.json"):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        image = trace.get("input_image")
        digest = image.get("sha256") if isinstance(image, dict) else None
        full_name = trace.get("full_result_file")
        business_name = trace.get("business_view_file")
        if (
            isinstance(digest, str)
            and isinstance(full_name, str)
            and isinstance(business_name, str)
            and (RESULTS_DIR / full_name).is_file()
            and (RESULTS_DIR / business_name).is_file()
        ):
            hashes.add(digest)
    return hashes


def _copy_result_artifacts(output: ExtractionOutput, batch_dir: Path) -> dict[str, str]:
    """把页面业务视图和完整追溯副本集中到批次目录。"""

    result_id = output.result_id
    targets = {
        "full_result": batch_dir / "full_results" / output.full_result_path.name,
        "business_view": batch_dir / "business_views" / output.business_view_path.name,
    }
    trace_path = RESULTS_DIR / ".metadata" / f"{result_id}.json"
    if trace_path.is_file():
        targets["trace"] = batch_dir / "traces" / trace_path.name
    for source_key, target in targets.items():
        source = {
            "full_result": output.full_result_path,
            "business_view": output.business_view_path,
            "trace": trace_path,
        }[source_key]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return {
        name: str(path.relative_to(batch_dir))
        for name, path in targets.items()
    }


def _failure_record(error: Exception) -> dict[str, Any]:
    return {
        "error": str(error),
        "diagnostic_id": getattr(error, "diagnostic_id", None),
        "diagnostics": getattr(error, "issues", []),
    }


def _extract_one(
    image: ArchiveImage,
    *,
    model_id: str,
    retry_count: int,
    batch_dir: Path,
    active_state: dict[str, int],
    active_lock: Lock,
) -> dict[str, Any]:
    """单图最多提交 `retry_count + 1` 次，失败诊断保留每次记录。"""

    image_path = PROJECT_ROOT / image.extracted_path
    content_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
    attempts: list[dict[str, Any]] = []
    started_at = _utc_now()
    with active_lock:
        active_state["active"] += 1
        active_state["maximum"] = max(active_state["maximum"], active_state["active"])
    try:
        for attempt_number in range(1, retry_count + 2):
            attempt_started = perf_counter()
            try:
                output = run_design_dna_extraction(
                    image_path=image_path,
                    content_type=content_type,
                    model_id=model_id,
                    user_prompt="",
                )
            except Exception as exc:  # noqa: BLE001 - 任何单图异常都必须留痕后再决定是否重试。
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "status": "failed",
                        "duration_seconds": round(perf_counter() - attempt_started, 3),
                        **_failure_record(exc),
                    }
                )
                continue
            artifacts = _copy_result_artifacts(output, batch_dir)
            attempts.append(
                {
                    "attempt": attempt_number,
                    "status": "completed",
                    "duration_seconds": round(perf_counter() - attempt_started, 3),
                    "result_id": output.result_id,
                    "artifacts": artifacts,
                }
            )
            return {
                "image": asdict(image),
                "status": "completed",
                "started_at": started_at,
                "completed_at": _utc_now(),
                "attempts": attempts,
            }
        return {
            "image": asdict(image),
            "status": "failed",
            "started_at": started_at,
            "completed_at": _utc_now(),
            "attempts": attempts,
        }
    finally:
        with active_lock:
            active_state["active"] -= 1


def _run_group(
    images: list[ArchiveImage],
    *,
    model_id: str,
    retry_count: int,
    batch_dir: Path,
    workers: int,
    state: dict[str, Any],
    active_state: dict[str, int],
    active_lock: Lock,
    replace_existing: bool = False,
) -> list[dict[str, Any]]:
    """以固定并发执行一组图片，并在每张结束后刷新断点清单。"""

    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dna-archive") as executor:
        futures: dict[Future[dict[str, Any]], ArchiveImage] = {
            executor.submit(
                _extract_one,
                image,
                model_id=model_id,
                retry_count=retry_count,
                batch_dir=batch_dir,
                active_state=active_state,
                active_lock=active_lock,
            ): image
            for image in images
        }
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            if replace_existing:
                image_path = record["image"]["extracted_path"]
                previous_item = next(
                    (
                        item
                        for item in state["items"]
                        if item["image"]["extracted_path"] == image_path
                    ),
                    None,
                )
                if previous_item is not None:
                    # 续跑失败项时保留前一轮的完整失败记录，避免用新尝试覆盖旧诊断。
                    record["rerun_history"] = [
                        *previous_item.get("rerun_history", []),
                        {
                            "rerun_started_at": state["updated_at"],
                            "status": previous_item["status"],
                            "started_at": previous_item["started_at"],
                            "completed_at": previous_item["completed_at"],
                            "attempts": previous_item["attempts"],
                        },
                    ]
                    state["items"].remove(previous_item)
            state["items"].append(record)
            state["updated_at"] = _utc_now()
            _atomic_json_write(batch_dir / "manifest.json", state)
            image_name = Path(record["image"]["extracted_path"]).name
            print(f"[{record['status']}] {image_name}", flush=True)
    return records


def run_batch(
    archive_paths: list[Path],
    *,
    batch_dir: Path,
    model_id: str,
    workers: int,
    retry_count: int,
    preflight_size: int,
    dry_run: bool = False,
    resume: bool = False,
    rerun_failures: bool = False,
    rerun_limit: int | None = None,
    skip_existing_success: bool = False,
) -> dict[str, Any]:
    """解压、预检并执行批量 DNA 提取，返回最终清单。"""

    if resume and rerun_failures:
        raise ArchiveBatchError("断点续跑和失败重跑不能同时指定")
    if rerun_limit is not None and (not rerun_failures or rerun_limit < 1):
        raise ArchiveBatchError("--rerun-limit 只能与正数的 --rerun-failures 一起使用")
    if skip_existing_success and (resume or rerun_failures):
        raise ArchiveBatchError("已成功图片过滤只在新批次创建时指定")
    if workers != 5:
        raise ArchiveBatchError("本批次按用户要求固定使用 5 个并发槽位")
    if retry_count != 1:
        raise ArchiveBatchError("本批次按用户要求固定为失败后重试 1 次")
    existing_state: dict[str, Any] | None = None
    if batch_dir.exists() and any(batch_dir.iterdir()):
        manifest_path = batch_dir / "manifest.json"
        try:
            existing_state = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArchiveBatchError(f"批次输出目录必须为空：{batch_dir}") from exc
        # dry-run 已安全写入图片时允许原目录继续，任何已提交过模型的批次仍拒绝覆盖。
        if not (
            (existing_state.get("status") == "prepared" and existing_state.get("items") == [])
            or (resume and existing_state.get("status") == "running")
            or (rerun_failures and existing_state.get("status") == "partial")
        ):
            raise ArchiveBatchError(f"批次输出目录必须为空：{batch_dir}")
    elif resume or rerun_failures:
        raise ArchiveBatchError("续跑或失败重跑只能用于已有批次")
    images = extract_archives(archive_paths, batch_dir / "images")
    if resume or rerun_failures:
        assert existing_state is not None
        if existing_state.get("model_id") != model_id:
            raise ArchiveBatchError("续跑的模型必须与原批次一致")
        if existing_state.get("image_count") != len(images):
            raise ArchiveBatchError("续跑图片数量与原批次不一致")
        state = existing_state
        state["resumed_at"] = _utc_now()
        state["updated_at"] = _utc_now()
        if rerun_failures:
            previous_failures = [
                item for item in state.get("items", []) if item["status"] == "failed"
            ]
            if not previous_failures:
                raise ArchiveBatchError("该批次没有可重跑的失败图片")
            history_dir = batch_dir / "failure_history"
            history_dir.mkdir(parents=True, exist_ok=True)
            history_path = history_dir / f"rerun_{len(list(history_dir.glob('*.json'))) + 1}_before.json"
            _atomic_json_write(history_path, previous_failures)
            failed_paths = {
                item["image"]["extracted_path"] for item in previous_failures
            }
            pending_images = [
                image for image in images if image.extracted_path in failed_paths
            ]
            if rerun_limit is not None:
                pending_images = pending_images[:rerun_limit]
            state["failure_reruns"] = state.get("failure_reruns", 0) + 1
        else:
            processed_paths = {
                item["image"]["extracted_path"] for item in state.get("items", [])
            }
            skipped_paths = {
                item["extracted_path"] for item in state.get("skipped_existing", [])
            }
            pending_images = [
                image
                for image in images
                if image.extracted_path not in processed_paths
                and image.extracted_path not in skipped_paths
            ]
    else:
        successful_hashes = _successful_result_hashes() if skip_existing_success else set()
        skipped_existing = [
            asdict(image) for image in images if image.sha256 in successful_hashes
        ]
        pending_images = [
            image for image in images if image.sha256 not in successful_hashes
        ]
        state = {
            "schema_version": "design_dna_archive_batch_v1",
            "status": "prepared" if dry_run else "running",
            "model_id": model_id,
            "requested_workers": workers,
            "requested_retry_count": retry_count,
            "preflight_size": min(preflight_size, len(pending_images)),
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "archives": [str(path.relative_to(PROJECT_ROOT)) for path in archive_paths],
            "image_count": len(images),
            "skipped_existing": skipped_existing,
            "items": [],
        }
    _atomic_json_write(batch_dir / "manifest.json", state)
    if dry_run:
        return state

    active_state = {"active": 0, "maximum": 0}
    active_lock = Lock()
    if not resume and not rerun_failures:
        preflight_images = pending_images[:preflight_size]
        pending_images = pending_images[preflight_size:]
        preflight_started = perf_counter()
        preflight_records = _run_group(
            preflight_images,
            model_id=model_id,
            retry_count=retry_count,
            batch_dir=batch_dir,
            workers=workers,
            state=state,
            active_state=active_state,
            active_lock=active_lock,
        )
        state["preflight"] = {
            "duration_seconds": round(perf_counter() - preflight_started, 3),
            "completed": sum(record["status"] == "completed" for record in preflight_records),
            "failed": sum(record["status"] == "failed" for record in preflight_records),
            "maximum_observed_workers": active_state["maximum"],
        }
        state["updated_at"] = _utc_now()
        _atomic_json_write(batch_dir / "manifest.json", state)
        if preflight_records and all(record["status"] == "failed" for record in preflight_records):
            # 即使预检整体中止，也要提供与完整批次相同的失败清单，便于页面或人工追查。
            _atomic_json_write(batch_dir / "failures.json", preflight_records)
            state["status"] = "aborted_after_preflight"
            state["completed_at"] = _utc_now()
            _atomic_json_write(batch_dir / "manifest.json", state)
            raise ArchiveBatchError("5 路预检全部失败，已停止后续图片以避免重复消耗")

    _run_group(
        pending_images,
        model_id=model_id,
        retry_count=retry_count,
        batch_dir=batch_dir,
        workers=workers,
        state=state,
        active_state=active_state,
        active_lock=active_lock,
        replace_existing=rerun_failures,
    )
    failures = [item for item in state["items"] if item["status"] == "failed"]
    _atomic_json_write(batch_dir / "failures.json", failures)
    state["status"] = "completed" if not failures else "partial"
    state["completed_at"] = _utc_now()
    state["summary"] = {
        "completed": len(state["items"]) - len(failures),
        "failed": len(failures),
        "skipped_existing": len(state.get("skipped_existing", [])),
        "maximum_observed_workers": max(
            active_state["maximum"],
            state.get("preflight", {}).get("maximum_observed_workers", 0),
        ),
    }
    _atomic_json_write(batch_dir / "manifest.json", state)
    return state


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path, help="待解压的图片 ZIP")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--workers", default=5, type=int)
    parser.add_argument("--retries", default=1, type=int)
    parser.add_argument("--preflight-size", default=5, type=int)
    parser.add_argument(
        "--skip-existing-success",
        action="store_true",
        help="按图片内容哈希跳过已存在完整结果与页面视图的图片",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true", help="续跑被人工中断的 running 批次")
    parser.add_argument(
        "--rerun-failures",
        action="store_true",
        help="对 partial 批次的失败图片另起一轮最多一次重试，并保留旧失败记录",
    )
    parser.add_argument(
        "--rerun-limit",
        type=int,
        help="失败重跑时只处理前 N 张，用于确认外部额度或服务恢复",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    archive_paths = [path.resolve() for path in args.archives]
    if any(not path.is_file() for path in archive_paths):
        missing = [str(path) for path in archive_paths if not path.is_file()]
        raise ArchiveBatchError(f"未找到压缩包：{', '.join(missing)}")
    output_dir = args.output_dir.resolve()
    result = run_batch(
        archive_paths,
        batch_dir=output_dir,
        model_id=args.model,
        workers=args.workers,
        retry_count=args.retries,
        preflight_size=args.preflight_size,
        dry_run=args.dry_run,
        resume=args.resume,
        rerun_failures=args.rerun_failures,
        rerun_limit=args.rerun_limit,
        skip_existing_success=args.skip_existing_success,
    )
    print(json.dumps(result.get("summary") or {"image_count": result["image_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

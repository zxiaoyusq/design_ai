"""审计真实运行并打包离线交付；进行中快照不报告完成，缺失用量不补零。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any
import zipfile
from zoneinfo import ZoneInfo


SECRET_KEYS = {"access_token", "refresh_token", "id_token", "api_key", "openai_api_key", "client_secret", "private_key"}
CALL_FILES = {"receipt.json", "answer.json", "schema.json", "prompt.txt", "system.txt"}
DENIED_NAMES = {"auth.json", "credentials.json", "secrets.json", "token.json", "tokens.json", ".env"}


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def file_ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": digest(path)}


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def check_text(path: Path, raw: bytes) -> None:
    """结构化结果可带认证方式布尔信息，不能带认证值、私钥或图片请求base64。"""
    if path.name.lower() in DENIED_NAMES or path.suffix.lower() in {".pem", ".key"}:
        raise ValueError(f"拒绝打包认证文件：{path.name}")
    # 检测带编码正文的真实密钥块；源码中的检测常量本身不含密钥，不能误拒代码快照。
    private_key_block = re.search(rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----(?:\\[rn]|\s)+[A-Za-z0-9+/=]{32,}", raw)
    if re.search(rb"data:image/[^;,\s]+;base64,", raw) or private_key_block:
        raise ValueError(f"拒绝打包内嵌请求图片或私钥：{path.name}")
    if path.suffix in {".json", ".jsonl"}:
        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key.casefold() in SECRET_KEYS and isinstance(child, str) and child.strip():
                        raise ValueError(f"拒绝打包含认证值的字段：{path.name} / {key}")
                    if key.casefold() == "authorization" and isinstance(child, str) and child.lower().startswith("bearer "):
                        raise ValueError(f"拒绝打包认证头：{path.name}")
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        if path.suffix == ".jsonl":
            for line in raw.splitlines():
                if line.strip():
                    walk(json.loads(line))
        else:
            walk(json.loads(raw))


def copy_checked(source: Path, target: Path, expected: str | None = None) -> dict:
    if source.is_symlink():
        raise ValueError(f"交付输入不允许符号链接：{source}")
    raw = source.read_bytes()
    if source.suffix.lower() in {".json", ".jsonl", ".txt", ".md", ".py", ".cjs", ".js", ".yaml", ".html"}:
        check_text(source, raw)
    source_sha = digest_bytes(raw)
    if expected is not None and source_sha != expected:
        raise ValueError(f"来源文件SHA不符：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)
    return {"source_path": str(source.resolve()), "sha256": source_sha, "bytes": len(raw)}


def within(path: Path, directory: Path) -> bool:
    return path.resolve().is_relative_to(directory.resolve())


def late_completions(run_dir: Path, excluded_dirs: list[Path]) -> dict[str, dict]:
    """晚到结果必须绑定原调用及冻结日志，不能靠另一份同目录回执悄悄替换失败。"""
    recoveries: dict[str, dict] = {}
    for path in sorted(run_dir.rglob("completion-recovery.json")):
        if any(within(path, directory) for directory in excluded_dirs):
            continue
        data = read(path)
        if data.get("schema_version") != "prism.late-completion-recovery.v1":
            continue
        if data.get("additional_model_calls") != 0 or data.get("original_host_timeout_preserved") is not True:
            raise ValueError(f"晚到记录没有保留原调用边界：{path}")
        invocation = str(Path(data["original_invocation_dir"]).resolve())
        # 原失败日志可能继续追加，校验原SHA对应的独立前缀，而非要求可变原日志仍相同。
        required = ("original_receipt_ref", "original_receipt_snapshot_ref", "original_events_verified_prefix_ref", "late_events_ref", "late_raw_answer_ref", "late_answer_ref", "late_receipt_ref")
        if any(not isinstance(data.get(key), dict) for key in required):
            raise ValueError(f"晚到记录缺少完整证据：{path}")
        for ref in data.values():
            if isinstance(ref, dict) and "path" in ref and "sha256" in ref:
                if digest(Path(ref["path"])) != ref["sha256"]:
                    raise ValueError(f"晚到证据SHA不符：{ref['path']}")
        original, late = read(Path(data["original_receipt_ref"]["path"])), read(Path(data["late_receipt_ref"]["path"]))
        if data["original_receipt_snapshot_ref"]["sha256"] != data["original_receipt_ref"]["sha256"] or original.get("events_ref", {}).get("sha256") != data["original_events_verified_prefix_ref"]["sha256"]:
            raise ValueError(f"晚到记录没有匹配原超时收据和日志：{path}")
        if (late.get("original_invocation_dir") != invocation or late.get("original_receipt_ref") != data["original_receipt_ref"]
                or late.get("additional_model_calls") != 0 or late.get("usage") != data.get("usage")
                or late.get("started_at") != original.get("started_at") or late.get("requested_model") != original.get("requested_model")
                or not isinstance(late.get("completed_turn_count"), int) or late["completed_turn_count"] < 1
                or not isinstance(data.get("usage", {}).get("requests_with_usage"), int) or data["usage"]["requests_with_usage"] < 1):
            raise ValueError(f"晚到回执不能证明同一请求的实际完成用量：{path}")
        recovery = {"recovery_ref": file_ref(path), "record": data, "receipt": late}
        previous = recoveries.get(invocation)
        if previous and previous["recovery_ref"]["sha256"] != recovery["recovery_ref"]["sha256"]:
            raise ValueError(f"同一原调用有冲突晚到记录：{invocation}")
        recoveries[invocation] = recovery
    return recoveries


def metadata_allowed(source: Path, run_dir: Path, late_evidence_paths: set[Path]) -> bool:
    """普通调用只复制白名单；额外日志仅限已核SHA的晚到证据，仍走认证检查。"""
    if source.name.lower() in DENIED_NAMES or source.name in {"payload.json", "request.json"}:
        return False
    if source.resolve() in late_evidence_paths:
        return True
    # 有界补查使用call-01等实际调用目录，同样只收入提示词/模式/答案/回执白名单。
    in_call = any(part in {"call", "calls", "model-calls"} or re.fullmatch(r"call-\d+", part) for part in source.relative_to(run_dir).parts)
    if in_call:
        return source.name in CALL_FILES
    return source.suffix.lower() in {".json", ".md", ".py", ".cjs", ".yaml"}


def package_board_captures(run_dir: Path, excluded_dirs: list[Path], accounting: dict, package_root: Path) -> dict:
    """只收模型实际审阅的板图；按图像字节去重，保留原路径、审阅绑定及取景旁证。"""
    references = []
    receipt_paths = {
        Path(ref["path"]) for call in accounting["calls"]
        for ref in (call.get("receipt_ref"), call.get("effective_receipt_ref")) if ref
    }
    for path in sorted(receipt_paths):
        for index, row in enumerate(read(path).get("images", [])):
            if row.get("role") == "actual_board_grid":
                references.append({"capture_ref": {key: row[key] for key in ("path", "sha256")}, "board_id": row.get("candidate_id"), "binding_ref": file_ref(path), "binding_pointer": f"images[{index}]", "kind": "actual_model_input"})
    for path in sorted(run_dir.rglob("reviews.json")):
        if any(within(path, directory) for directory in excluded_dirs):
            continue
        data = read(path)
        if not isinstance(data, dict):
            continue
        for index, review in enumerate(data.get("reviews", [])):
            ref = review.get("provenance", {}).get("board_capture_ref")
            if ref:
                references.append({"capture_ref": ref, "board_id": review.get("board_id"), "binding_ref": file_ref(path), "binding_pointer": f"reviews[{index}].provenance.board_capture_ref", "kind": "independent_review_provenance"})
    captures = {}
    for reference in references:
        ref = reference["capture_ref"]
        source, sha = Path(ref["path"]), ref["sha256"]
        if source.suffix.lower() != ".png" or not source.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"真实板审输入不是PNG：{source}")
        if digest(source) != sha:
            raise ValueError(f"真实板审输入SHA不符：{source}")
        sidecar = source.with_name(source.name + ".json")
        if not sidecar.is_file():
            raise ValueError(f"真实板审输入缺少对应取景旁证：{sidecar}")
        sidecar_data, sidecar_sha = read(sidecar), digest(sidecar)
        if sidecar_data.get("screenshot_ref", {}).get("sha256") != sha or (reference.get("board_id") and sidecar_data.get("board_id") != reference["board_id"]):
            raise ValueError(f"板审截图旁证没有匹配图像与板ID：{sidecar}")
        if sha not in captures:
            relative = Path("audit/board-captures") / f"{sha}.png"
            captures[sha] = {"package_path": relative.as_posix(), **copy_checked(source, package_root / relative, sha), "source_aliases": [], "board_ids": [], "review_bindings": [], "sidecars": []}
        capture = captures[sha]
        if str(source.resolve()) not in capture["source_aliases"]:
            capture["source_aliases"].append(str(source.resolve()))
        if reference.get("board_id") and reference["board_id"] not in capture["board_ids"]:
            capture["board_ids"].append(reference["board_id"])
        capture["review_bindings"].append({key: value for key, value in reference.items() if key != "capture_ref"})
        copied_sidecar = next((row for row in capture["sidecars"] if row["sha256"] == sidecar_sha), None)
        if copied_sidecar is None:
            relative = Path("audit/board-captures") / f"{sha}.{sidecar_sha[:12]}.png.json"
            copied_sidecar = {"package_path": relative.as_posix(), **copy_checked(sidecar, package_root / relative, sidecar_sha), "source_aliases": []}
            capture["sidecars"].append(copied_sidecar)
        if str(sidecar.resolve()) not in copied_sidecar["source_aliases"]:
            copied_sidecar["source_aliases"].append(str(sidecar.resolve()))
    result = {"schema_version": "prism.actual_review_board_captures.v1", "capture_count": len(captures), "capture_refs_count": len(references), "captures": list(captures.values()), "scope": "仅实际独立板审receipt或review引用的整板PNG；不包含仅用于功能测试的其他截图。"}
    write(package_root / "audit/board-captures/index.json", result)
    return result


def account_calls(run_dir: Path, excluded_dirs: list[Path]) -> dict:
    """按真实请求目录归并回执副本，保留所有失败及无法确认的网络/用量信息。"""
    recoveries = late_completions(run_dir, excluded_dirs)
    records: dict[str, dict] = {}
    for path in sorted(run_dir.rglob("receipt.json")):
        if any(within(path, directory) for directory in excluded_dirs):
            continue
        data = read(path)
        if "requested_model" not in data or "started_at" not in data:
            continue
        if data.get("original_invocation_dir"):
            invocation = str(Path(data["original_invocation_dir"]).resolve())
            recovery = recoveries.get(invocation)
            if not recovery or digest(path) != recovery["record"]["late_receipt_ref"]["sha256"]:
                raise ValueError(f"补充回执缺少已绑定的晚到恢复记录：{path}")
            continue
        prompt_path = data.get("prompt_ref", {}).get("path")
        invocation = str(Path(prompt_path).parent.resolve()) if prompt_path else str(path.parent.resolve())
        previous = records.get(invocation)
        record = {"invocation_directory": invocation, "receipt_ref": file_ref(path), "receipt_aliases": [str(path.resolve())],
                  **{key: data.get(key) for key in ("framework", "deepagents_version", "transport", "requested_model", "requested_reasoning_effort", "actual_model", "actual_provider", "actual_service_tier", "reported_models", "started_at", "finished_at", "status", "failure", "exit_code", "usage", "completed_turn_count", "actual_http_request_count", "cli_internal_http_retry_count", "observed_reconnect_diagnostic_count", "websocket_to_https_observed")}}
        if previous:
            if previous["receipt_ref"]["sha256"] != record["receipt_ref"]["sha256"]:
                raise ValueError(f"同一实际请求目录出现不同回执，须先澄清：{invocation}")
            previous["receipt_aliases"].append(str(path.resolve()))
        else:
            records[invocation] = record
    for invocation, recovery in recoveries.items():
        call = records.get(invocation)
        data, late = recovery["record"], recovery["receipt"]
        if not call or call["receipt_ref"]["sha256"] != data["original_receipt_ref"]["sha256"]:
            raise ValueError(f"晚到恢复没有匹配本次审计的原请求回执：{invocation}")
        call["original_host_result"] = {key: call.get(key) for key in ("receipt_ref", "status", "failure", "exit_code", "finished_at", "usage", "completed_turn_count")}
        call["late_completion"] = {"recovery_ref": recovery["recovery_ref"], **data}
        call["effective_receipt_ref"] = data["late_receipt_ref"]
        # 晚到回合替换同一请求未知用量，既不叠加原占位0，也不增加调用次数。
        for key in ("usage", "completed_turn_count", "status", "failure", "exit_code", "finished_at", "actual_model", "actual_provider", "actual_service_tier", "reported_models", "actual_http_request_count", "cli_internal_http_retry_count", "observed_reconnect_diagnostic_count", "websocket_to_https_observed"):
            call[key] = late.get(key)
    calls = list(records.values())
    for call in calls:
        usage = call.get("usage") or {}
        completed = call.get("completed_turn_count")
        has_turn_usage = (
            isinstance(completed, int) and completed > 0
            and isinstance(usage.get("requests_with_usage"), int) and usage["requests_with_usage"] > 0
        )
        # 失败适配器会写数值0；没有完成回合时这些值不代表已知零成本。
        call["completed_turn_usage_available"] = has_turn_usage
        call["reported_usage_complete"] = has_turn_usage and usage.get("usage_complete") is True
        call["zero_fields_without_completed_usage"] = not has_turn_usage and all(
            usage.get(key) == 0 for key in ("input_tokens", "output_tokens", "total_tokens")
        )
    token_fields = ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens")
    totals = {name: sum((call.get("usage") or {}).get(name) or 0 for call in calls) for name in token_fields}
    unknown = {name: sum(not isinstance((call.get("usage") or {}).get(name), int) for call in calls) for name in token_fields}
    active = []
    for path in sorted(run_dir.rglob("request.json")):
        if any(within(path, directory) for directory in excluded_dirs):
            continue
        # 只识别调用目录；请求文件尚无最终回执时，不能把已知用量称为全量。
        if path.parent.name and not path.with_name("receipt.json").exists() and (path.with_name("prompt.txt").exists() or path.with_name("schema.json").exists()):
            active.append(str(path.parent.resolve()))
    unknown_usage = {name: sum(not call["completed_turn_usage_available"] or not isinstance((call.get("usage") or {}).get(name), int) for call in calls) for name in token_fields}
    reported_usage_complete = bool(calls) and not active and all(call["reported_usage_complete"] for call in calls) and not any(unknown.values())
    provider_attempts_known = bool(calls) and all(isinstance(call["actual_http_request_count"], int) for call in calls)
    return {
        "schema_version": "prism.dna_cluster_execution_accounting.v1", "calls": calls,
        "invocation_count": len(calls), "status_counts": dict(Counter(call.get("status") or "unknown" for call in calls)),
        "original_host_status_counts": dict(Counter((call.get("original_host_result") or call).get("status") or "unknown" for call in calls)),
        "late_completion_invocation_count": len(recoveries), "additional_model_calls_from_late_recovery": 0,
        "known_token_totals_lower_bound": totals, "calls_missing_token_fields": unknown,
        "calls_without_completed_turn_usage": sum(not call["completed_turn_usage_available"] for call in calls),
        "calls_with_incomplete_reported_usage": sum(not call["reported_usage_complete"] for call in calls),
        "calls_zero_fields_without_completed_usage": sum(call["zero_fields_without_completed_usage"] for call in calls),
        "calls_without_known_usage_by_field": unknown_usage,
        "reported_completed_turn_usage_complete": reported_usage_complete,
        "all_usage_complete": reported_usage_complete and provider_attempts_known,
        "requests_without_final_receipt": active,
        "actual_http_request_count": sum(call["actual_http_request_count"] for call in calls) if calls and all(isinstance(call["actual_http_request_count"], int) for call in calls) else None,
        "usage_is_billing_statement": False,
        "count_basis": "独立原请求目录；副本合并，晚到完成按original_invocation_dir更新同次请求用量，保留原超时证据且不增加调用。历史DNA复用不增加调用。失败且无完成回合的0字段不是零成本。完成回合用量不等于所有底层HTTP请求已知。",
    }


def package(args: argparse.Namespace) -> dict:
    run_dir, delivery, output = args.run_dir.resolve(), args.delivery.resolve(), args.out.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"输出目录须为空：{output}")
    if within(output, delivery) or within(delivery, output):
        raise ValueError("输出目录与离线交付目录不能互相包含")
    sample_path = args.sample or run_dir / "sample.json"
    observation_path = args.observations or run_dir / "observations.json"
    sample, observations = read(sample_path), read(observation_path)
    manifest = read(delivery / "delivery-manifest.json")
    if manifest.get("schema_version") != "prism.dna_cluster_delivery.v1":
        raise ValueError("不是当前新路线的离线交付格式")
    if digest(delivery / manifest["index"]["path"]) != manifest["index"]["sha256"]:
        raise ValueError("交付首页已不同于其manifest")
    for asset in manifest["assets"]:
        if digest(delivery / asset["path"]) != asset["sha256"]:
            raise ValueError(f"交付原图已不同于其manifest：{asset['path']}")
    for board in manifest["boards"]:
        if digest(delivery / board["path"]) != board["html_sha256"]:
            raise ValueError(f"交付图板已不同于其manifest：{board['board_id']}")
    selected = {row["sha256"] for row in sample["images"]}
    observed_rows = {row["sha256"]: row for row in observations["images"]}
    if set(observed_rows) != selected or len(observations["images"]) != len(sample["images"]):
        raise ValueError("观察台账没有完整对应冻结样本，不能打包为当前试跑")
    counts = dict(Counter(row.get("status", "unknown") for row in observations["images"]))
    accounting = account_calls(run_dir, [delivery, output])
    sample_ref, observation_ref = file_ref(sample_path), file_ref(observation_path)
    delivery_is_current = manifest["inputs"]["sample.json"]["sha256"] == sample_ref["sha256"] and manifest["inputs"]["observations.json"]["sha256"] == observation_ref["sha256"]
    unsettled = sum(value for status, value in counts.items() if status not in {"observed", "failed"})
    all_boards_reviewed = all(board.get("validation") is not None for board in manifest["boards"])
    if args.mode == "final" and (unsettled or accounting["requests_without_final_receipt"] or not delivery_is_current or not all_boards_reviewed):
        raise ValueError("仍有待处理图片、未结束调用、交付输入版本不同或板审未编译；请保留snapshot而不是宣称最终完成")
    output.mkdir(parents=True, exist_ok=True)
    package_root = output / "offline"
    package_root.mkdir()
    packaged_sources = []
    # 成板使用的原图和旧版交付原样复制；其余样本保留完整路径和来源清单。
    for source in sorted(delivery.rglob("*")):
        if source.is_file():
            relative = source.relative_to(delivery)
            if source.suffix.lower() not in {".html", ".json", ".js", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
                raise ValueError(f"离线交付含未约定文件：{relative}")
            packaged_sources.append({"package_path": relative.as_posix(), **copy_checked(source, package_root / relative)})
    image_audit = []
    for row in sample["images"]:
        path = Path(row["local_path"])
        actual = digest(path) if path.is_file() else None
        image_audit.append({"image_id": row["image_id"], "sha256": row["sha256"], "local_path": str(path), "recomputed_sha256": actual, "verified": actual == row["sha256"], "status": observed_rows[row["sha256"]].get("status"), "aliases": row.get("aliases", []), "sources": row.get("sources", [])})
    if not all(row["verified"] for row in image_audit):
        write(output / "failed-original-image-audit.json", image_audit)
        raise ValueError("样本原图SHA核验失败，已保留失败清单")
    write(package_root / "audit/original-image-audit.json", {"scope": "全部冻结样本原图；全集pool未抽中图片仅保留原索引SHA，未在此重新读取原图", "image_count": len(image_audit), "verified_count": len(image_audit), "images": image_audit})
    write(package_root / "audit/execution-accounting.json", accounting)
    actual_board_captures = package_board_captures(run_dir, [delivery, output], accounting, package_root)
    late_evidence = {
        Path(ref["path"]).resolve(): ref["sha256"]
        for call in accounting["calls"] for ref in (call.get("late_completion") or {}).values()
        if isinstance(ref, dict) and "path" in ref and "sha256" in ref
    }
    metadata_refs = []
    for source in sorted(run_dir.rglob("*")):
        if not source.is_file() or any(within(source, directory) for directory in (delivery, output)):
            continue
        relative = source.relative_to(run_dir)
        if not metadata_allowed(source, run_dir, set(late_evidence)):
            continue
        if source.name in {"package-manifest.json", "package-verification.json", "execution-accounting.json", "original-image-audit.json"}:
            continue
        destination = package_root / "audit/run-metadata" / relative
        metadata_refs.append({"package_path": destination.relative_to(package_root).as_posix(), **copy_checked(source, destination, late_evidence.get(source.resolve()))})
    # 历史R5原结果也作为文本交接，来源别名保留；同字节版本只复制一次。
    legacy = {}
    for row in sample["images"]:
        for dna in row.get("dna_refs", []):
            for dna_ref in [dna] + ([dna["record_ref"]] if dna.get("record_ref") else []):
                key = dna_ref["sha256"]
                if key not in legacy:
                    destination = package_root / "audit/legacy-dna" / f"{key}.json"
                    legacy[key] = {"package_path": destination.relative_to(package_root).as_posix(), **copy_checked(Path(dna_ref["path"]), destination, key), "image_sha256": [], "source_aliases": []}
                if row["sha256"] not in legacy[key]["image_sha256"]:
                    legacy[key]["image_sha256"].append(row["sha256"])
                if dna_ref["path"] not in legacy[key]["source_aliases"]:
                    legacy[key]["source_aliases"].append(dna_ref["path"])
    write(package_root / "audit/legacy-dna-index.json", list(legacy.values()))
    status = "final_snapshot_with_unresolved_results" if args.mode == "final" and (counts.get("failed", 0) or any(board.get("status") != "ready_for_designer_feedback" for board in manifest["boards"])) else "final_snapshot" if args.mode == "final" else "in_progress_snapshot"
    summary = {
        "schema_version": "prism.dna_cluster_run_audit.v1", "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "status": status, "packaging_mode": args.mode, "run_dir": str(run_dir),
        "inputs": {"sample": sample_ref, "observations": observation_ref, "delivery_manifest": file_ref(delivery / "delivery-manifest.json"), "packager": file_ref(Path(__file__))},
        "image_count": len(sample["images"]), "image_status_counts": counts, "all_images_settled": unsettled == 0,
        "all_sample_original_SHA_verified": True, "delivery_uses_current_sample_and_observations": delivery_is_current,
        "board_count": manifest["board_count"], "board_status_counts": dict(Counter(board.get("status") or "unknown" for board in manifest["boards"])),
        "all_board_reviews_compiled": all_boards_reviewed,
        "prompt_versions_used": observations.get("prompt_versions_used"), "model_policy": observations.get("model_policy"),
        "execution": {key: value for key, value in accounting.items() if key != "calls"},
        "concurrency_audit": {
            "historical_actual_native_process_peak": None,
            "timeout_cleanup_refs": [file_ref(path) for path in sorted((run_dir / "timeout-cleanup").rglob("*.json"))],
            "contract_amendment_refs": [file_ref(path) for path in sorted((run_dir / "contract-amendments").rglob("*.json"))],
            "note": "合同并发上限仅为计划，不能据此确认实际历史峰值；已观察到的超时遗留进程及清理记录独立保留。",
        },
        "metadata_files": metadata_refs, "legacy_DNA_version_files": len(legacy), "delivery_original_asset_count": len(manifest["assets"]),
        "actual_review_board_capture_count": actual_board_captures["capture_count"], "actual_review_board_captures_index": "audit/board-captures/index.json",
        "model_calls_by_packager": 0, "visual_pass_awarded_by_packager": False, "designer_approval_awarded_by_packager": False,
        "credentials_and_raw_transport_payloads_included": False,
        "scope_note": "离线包用于浏览及文本追溯；全样本原图完整路径/SHA保留，实际图片只包含当前及显式历史图板使用的原图。进行中快照不代表本次样本执行结束。",
    }
    write(package_root / "audit/run-audit.json", summary)
    if args.mode == "final" and (digest(sample_path) != sample_ref["sha256"] or digest(observation_path) != observation_ref["sha256"]):
        raise ValueError("打包期间样本或观察仍在变化；停止最终包装并保留当前审计")
    files = [{"path": path.relative_to(package_root).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size} for path in sorted(package_root.rglob("*")) if path.is_file()]
    write(package_root / "package-manifest.json", {"schema_version": "prism.dna_cluster_offline_package.v1", "status": status, "files": files})
    archive_path = output / args.zip_name
    with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_root).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC校验失败")
        for row in files:
            if digest_bytes(archive.read(row["path"])) != row["sha256"]:
                raise ValueError(f"ZIP内文件SHA不一致：{row['path']}")
    verification = {"archive_ref": file_ref(archive_path), "bytes": archive_path.stat().st_size, "status": status, "CRC_verified": True, "manifest_SHA_verified": True, "file_count": len(files) + 1, "model_calls": 0}
    write(output / "package-verification.json", verification)
    print(json.dumps(verification, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, epilog="明确处理完本次样本和全部板审后用新目录--mode final；此标志仅请求最终核验，不能把pending改成完成。")
    parser.add_argument("--run-dir", type=Path, required=True, help="真实运行根目录，汇总其实际调用回执及版本元数据")
    parser.add_argument("--delivery", type=Path, required=True, help="render_delivery.py生成的离线交付目录")
    parser.add_argument("--out", type=Path, required=True, help="全新的审计及ZIP输出目录")
    parser.add_argument("--mode", choices=("snapshot", "final"), default="snapshot")
    parser.add_argument("--sample", type=Path, help="可选冻结样本路径，用于已归档试验快照")
    parser.add_argument("--observations", type=Path, help="可选冻结观察路径，用于已归档试验快照")
    parser.add_argument("--zip-name", default="prism-dna-moodboards-offline.zip")
    args = parser.parse_args()
    if Path(args.zip_name).name != args.zip_name or not args.zip_name.endswith(".zip"):
        raise ValueError("zip-name须为普通.zip文件名")
    package(args)


if __name__ == "__main__":
    main()

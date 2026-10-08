"""冻结 R5 原生 CLI 的网页薄适配；不改变提取请求或历史结果。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from app.agents.prism_dna_sol_r5 import (
    PRIMARY_PROMPT_PATH,
    PRIMARY_SCHEMA_PATH,
    PROMPT_VERSION,
    SKILL_NAME,
    SKILL_ROOT,
    FROZEN_MODEL,
)
from app.schemas.dna import ExtractionStage, ProgressEventLevel
from app.services.dna.storage import PROJECT_ROOT, RESULTS_DIR, _atomic_write, save_result_image
from app.services.visual_workflow.codex_transport import isolated_environment, verify_chatgpt_auth


RESULT_DIR = RESULTS_DIR / "d02"
RUN_DIR = RESULT_DIR / "r5_runs"


@dataclass(frozen=True)
class R5Output:
    result_id: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_exception(exc: Exception) -> str:
    """网关异常可能回显编码后的请求头；失败账本不能保存鉴权信息。"""

    message = str(exc)
    if "invalid header:" in message.lower():
        return f"{type(exc).__name__}: 网关返回 invalid header（头部明细已隐藏）"
    message = re.sub(r"(?i)Bearer\s+[^\s,}\"']+", "Bearer [REDACTED]", message)
    message = re.sub(r"[A-Za-z0-9_-]{256,}", "[长令牌已隐藏]", message)
    return f"{type(exc).__name__}: {message[:1000]}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


@lru_cache(maxsize=1)
def _portable():
    """包内 R5 冻结源码与资产哈希由原便携加载器验证，不复制另一套字段规则。"""

    path = SKILL_ROOT / "scripts" / "engine.py"
    spec = importlib.util.spec_from_file_location("prism_sol_r5_portable_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Sol R5 便携整理器不可读取")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.load_original()


def _reply(result: Any) -> str:
    messages = result.get("messages") if isinstance(result, dict) else None
    if not messages:
        raise ValueError("DeepAgent 没有返回消息")
    content = getattr(messages[-1], "content", messages[-1])
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            part if isinstance(part, str) else str(part.get("text", ""))
            for part in content if isinstance(part, (str, dict))
        ).strip()
    return str(content).strip()


def _answer(portable: Any, raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip().removeprefix("json").strip()
    answer = portable.loads(text)
    if not isinstance(answer, dict):
        raise ValueError("模型结果根节点必须是 JSON 对象")
    return answer


def validate_r5_request(model_id: str, user_prompt: str, reasoning_effort: str = "low") -> None:
    """网页仅选择图片；R5 模型、提示与参数均由冻结 CLI 确定。"""
    if model_id != FROZEN_MODEL or reasoning_effort != "low":
        raise ValueError("Sol R5 固定使用 gpt-6-sol / low / default / Fast 关闭，不能切换模型或推理档位")
    if user_prompt.strip():
        raise ValueError("Sol R5 使用冻结提取提示，不接受附加关注点；设计判断请在独立视觉审阅阶段完成")


def ensure_r5_execution_allowed() -> None:
    """只有新模型调用读取暂停边界；历史结果展示不受此限制。"""
    boundary_path = PROJECT_ROOT / "data/result/visual_workflow/h01_all13_20261005_expanded/execution-boundary.json"
    if boundary_path.is_file():
        boundary = json.loads(boundary_path.read_text(encoding="utf-8"))
        if boundary.get("all_model_calls_paused"):
            raise RuntimeError("模型调用已暂停；本次 Skill 更新不会启动新的 DNA 提取")


def run_prism_r5_extraction(
    *, image_path: Path, content_type: str, model_id: str, user_prompt: str,
    progress_callback: Any = None, source_record: dict[str, Any] | None = None,
    reasoning_effort: str = "low", single_request: bool = False,
) -> R5Output:
    """直接执行同事原始 CLI，仅把冻结输出包装成网页历史兼容格式。"""
    validate_r5_request(model_id, user_prompt, reasoning_effort)
    ensure_r5_execution_allowed()
    portable, engine = _portable()
    result_id = uuid4().hex
    run_dir = RUN_DIR / result_id
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC)
    timer = monotonic()
    image_path = image_path.resolve(strict=True)
    image_hash = _sha(image_path)
    metadata_path = image_path.parent / "metadata.json"
    source_metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else None
    image_id = image_hash[:32]
    environment = isolated_environment()
    verify_chatgpt_auth(environment)
    # 不复制算法、不再包裹提示，也不调用工程供应商；原 CLI 保存每个独立上下文的原始证据。
    command = [sys.executable, "-B", "-X", "utf8", str(SKILL_ROOT / "scripts/cli.py"),
               "parse", "--image", str(image_path), "--image-id", image_id,
               "--out", str(run_dir), "--execute"]
    if progress_callback:
        progress_callback(ExtractionStage.MODEL_ANALYSIS, "按冻结 Sol R5 CLI 解析原图，最多一次困难项复核", 12, ProgressEventLevel.INFO)
    try:
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                 env=environment, timeout=1300)
        if run_dir.is_dir():
            _atomic_write(run_dir / "web-cli.stdout.txt", process.stdout.encode("utf-8"))
            _atomic_write(run_dir / "web-cli.stderr.txt", process.stderr.encode("utf-8"))
            _write_json(run_dir / "web-invocation.json", {"command": command, "exit_code": process.returncode,
                        "model": FROZEN_MODEL, "transport": "codex_cli_chatgpt", "prompt_wrapped": False})
        if not (run_dir / "result.json").is_file():
            raise RuntimeError("原生 CLI 未产生提取结果，请查看运行记录；不重试、不切换模型")
        final = portable.read(run_dir / "result.json")
        if final.get("image_sha256") != image_hash or final.get("model") != FROZEN_MODEL:
            raise ValueError("原生结果图片身份或模型与冻结请求不一致")
        ledger = portable.read(run_dir / "call-ledger.json")
        primary_dir = run_dir / "calls" / ("P-" + image_id)
        focus_dir = run_dir / "calls" / ("F-" + image_id)
        primary_receipt = portable.read(primary_dir / "receipt.json")
        focus_receipt = portable.read(focus_dir / "receipt.json") if focus_dir.is_dir() else None
        # CLI 中困难项失败仍可产生 partial；保留原状态，不把原生未决结果包装成视觉合格。
        if not primary_receipt["schema_valid"]:
            raise ValueError("原生首次解析未通过结构校验")
        finished = datetime.now(UTC)
        payload = {
            "id": result_id, "skill": SKILL_NAME, "schema_version": "prism_sol_r5_candidate_v1",
            "image_name": image_path.name, "created_at": finished.isoformat(),
            "source": {"image_id": image_id, "image_sha256": image_hash, "image_filename": image_path.name,
                       "content_type": content_type, "upload_metadata": source_metadata,
                       "upload_metadata_sha256": _sha(metadata_path) if metadata_path.is_file() else None,
                       "research": source_record},
            "execution": {"model_id": FROZEN_MODEL, "adapter": "codex_cli_frozen_r5", "reasoning_effort": "low",
                          "service_tier_requested": "default", "actual_served_tier": "not_exposed", "fast_mode": False,
                          "user_prompt": "", "started_at": started.isoformat(), "finished_at": finished.isoformat(),
                          "duration_seconds": round(monotonic() - timer, 3), "prompt_version": PROMPT_VERSION,
                          "skill_sha256": _sha(SKILL_ROOT / "SKILL.md"), "prompt_asset_sha256": _sha(PRIMARY_PROMPT_PATH),
                          "schema_asset_sha256": _sha(PRIMARY_SCHEMA_PATH), "source_manifest_sha256": _sha(SKILL_ROOT / "assets/source-manifest.json"),
                          "algorithm_version": engine.VERSION, "max_calls": ledger["limit"], "automatic_retries": False,
                          "attempted_calls": len(ledger["calls"]), "primary_usage": primary_receipt.get("usage"),
                          "focus_usage": focus_receipt.get("usage") if focus_receipt else None,
                          "focus_error": focus_receipt.get("error") if focus_receipt else None,
                          "trace_dir": str(run_dir.relative_to(PROJECT_ROOT)), "native_status": final["status"],
                          "native_result_sha256": _sha(run_dir / "result.json"), "prompt_wrapped": False},
            "validation": {"primary_schema_valid": True, "focus_complete": not focus_receipt or focus_receipt["schema_valid"],
                           "pending_count": final["pending_count"], "invalid_count": len(final["invalid"]),
                           "full_216_visual_qualified": False, "human_gold_accuracy_established": False,
                           "note": "冻结 Sol R5 原生结果；网页仅适配展示，不赋予视觉审阅或偏好通过。"},
            "r5_result": final,
            "raw_responses": {"primary": (primary_dir / "answer.json").read_text(encoding="utf-8"),
                              "focus": (focus_dir / "answer.json").read_text(encoding="utf-8") if (focus_dir / "answer.json").is_file() else None},
        }
        path = RESULT_DIR / f"{result_id}.json"
        try:
            save_result_image(result_id, image_path)
            _write_json(path, payload)
        except Exception:
            (RESULTS_DIR / ".images" / f"{result_id}.webp").unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise
        return R5Output(result_id)
    except Exception as exc:
        # 原生失败记录保持原样，工程只补充一份安全的网页失败回执。
        if run_dir.is_dir():
            _write_json(run_dir / "web-failure.json", {"result_id": result_id, "failed_at": _now(), "error": _safe_exception(exc)})
        raise RuntimeError(f"Sol R5 提取失败；运行记录 {result_id}：{_safe_exception(exc)}") from exc

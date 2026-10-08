"""历史 R17 候选与批次结果的读取、追溯及冻结重跑实现。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator
from langchain_core.messages import HumanMessage

from app.agents.prism_image_dna import (
    PROMPT_PATH,
    PROMPT_VERSION,
    REVIEW_VERSION,
    SCHEMA_PATH,
    SKILL_NAME,
    SKILL_ROOT,
    create_primary_agent,
    create_review_agent,
)
from app.schemas.dna import ExtractionStage, ProgressEventLevel
from app.services.dna.storage import PROJECT_ROOT, RESULTS_DIR, _atomic_write, save_result_image
from app.services.llm.telemetry import ModelCallTelemetry


RESULT_DIR = RESULTS_DIR / "d02"
PPT_ENJOY_BATCH_ID = "ppt_enjoy_20260928_gemini38"
# 用户明确标记 ENJOY 的批次结果归用研目录；普通 D02 单图结果继续留在独立结果目录。
LIKED_IMAGES_RESULT_DIR = PROJECT_ROOT / "data" / "userreseach_data" / "liked_images_d02_results"
LIKED_IMAGES_PREVIEW_DIR = LIKED_IMAGES_RESULT_DIR / "images"
PPT_ENJOY_BATCH_MANIFEST = LIKED_IMAGES_RESULT_DIR / "batches" / PPT_ENJOY_BATCH_ID / "manifest.json"
RESULT_ID = re.compile(r"^[a-f0-9]{32}$")
CMF_FIELD_IDS = {"OPT-001", "OPT-002", "OPT-007", "TEX-002"}
MAX_REVIEW_OBSERVATIONS = 40


@dataclass(frozen=True)
class PrismOutput:
    """独立 D02 结果标识，不进入现有多标签结果库。"""

    result_id: str


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _dictionary() -> dict[str, Any]:
    """R41 提示内嵌原字典；仅解码核心槽位，不猜测附加字段。"""

    for line in PROMPT_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith('{"dictionary_version"'):
            return json.loads(line)
    raise RuntimeError("D02 R41 提示缺少原字典")


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part if isinstance(part, str) else part.get("text", "")
            for part in content
            if isinstance(part, (str, dict))
        )
    return str(content)


def _reply(result: dict[str, Any]) -> str:
    messages = result.get("messages") or []
    if not messages:
        raise ValueError("DeepAgent 没有返回消息")
    return _message_text(messages[-1]).strip()


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip().removeprefix("json").strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("模型输出中没有 JSON 对象")
    data, end = json.JSONDecoder().raw_decode(text[start:])
    if text[start + end :].strip():
        raise ValueError("模型 JSON 后还有非空内容")
    if not isinstance(data, dict):
        raise ValueError("模型 JSON 根节点必须是对象")
    return data


def _observations(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    dictionary = _dictionary()
    core_order = dictionary["core_category_order"]
    codes = dictionary["core_candidate_codes"]
    type_names = {item["wire_type"]: item["name"] for item in dictionary["types"]}
    observations: list[dict[str, Any]] = []
    for index, obj in enumerate(candidate.get("o", [])):
        if not isinstance(obj, dict):
            continue
        object_type = obj.get("t")
        fields = core_order.get(str(object_type), [])
        core = obj.get("c", "")
        if not isinstance(core, str):
            continue
        common = {
            "object_index": index,
            "object_type": object_type,
            "object_name": type_names.get(object_type, "未知对象"),
            "geometry": obj.get("g"),
        }
        values = obj.get("v")
        if isinstance(values, list) and values and isinstance(values[0], str):
            observations.append({**common, "field_id": "COL-006", "field_name": "颜色", "value": values[0]})
        open_index = 1
        for position, field_id in enumerate(fields):
            if position >= len(core):
                break
            code = core[position]
            open_value = None
            if code == "x":
                open_value = values[open_index] if isinstance(values, list) and open_index < len(values) else None
                open_index += 1
            if field_id not in CMF_FIELD_IDS or position >= len(core):
                continue
            if code in {"0", "9"}:
                continue
            definition = codes[field_id]
            value = definition["codes"].get(code)
            if code == "x":
                value = open_value if isinstance(open_value, str) else None
            if value:
                observations.append(
                    {**common, "field_id": field_id, "field_name": definition["name"], "value": value}
                )
    return observations


def _protocol_issues(candidate: dict[str, Any]) -> list[str]:
    """补足 Schema 无法表达的 R17 基础关系；不替代冻结 accept 全量审计。"""

    objects = candidate.get("o")
    if not isinstance(objects, list):
        return ["o 不是对象数组"]
    issues: list[str] = []
    parents: list[int | None] = []
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            issues.append(f"o[{index}] 不是对象")
            parents.append(None)
            continue
        geometry, core, values = obj.get("g"), obj.get("c"), obj.get("v")
        if index == 0 and obj.get("t") != 1:
            issues.append("o[0] 必须是产品整体 t=1")
        if not isinstance(geometry, list) or len(geometry) != 8 or not all(isinstance(x, int) for x in geometry):
            issues.append(f"o[{index}].g 必须是八个整数")
            parents.append(None)
            continue
        parent, x0, y0, x1, y1, ax, ay, z = geometry
        parents.append(parent)
        if parent < 0 or parent > len(objects) or parent == index + 1 or (index == 0 and parent != 0):
            issues.append(f"o[{index}].g 父对象编号无效")
        if not (0 <= x0 <= x1 <= 1000 and 0 <= y0 <= y1 <= 1000):
            issues.append(f"o[{index}].g 边界框无效")
        if not ((ax == ay == -1) or (x0 <= ax <= x1 and y0 <= ay <= y1)):
            issues.append(f"o[{index}].g 锚点未落在对象框内")
        if z not in {0, 1, 2, 3}:
            issues.append(f"o[{index}].g 纹理来源 z 无效")
        if isinstance(core, str) and isinstance(values, list) and len(values) != 1 + core.count("x"):
            issues.append(f"o[{index}].v 与开放核心槽数量不一致")
        fields = _dictionary()["core_category_order"].get(str(obj.get("t")), [])
        if "TEX-002" in fields and isinstance(core, str):
            texture_code = core[fields.index("TEX-002")]
            if texture_code not in {"0", "9"} and z == 0:
                issues.append(f"o[{index}] 有纹理核心值但 z=0")
    for start in range(len(parents)):
        seen: set[int] = set()
        current = start + 1
        while 1 <= current <= len(parents):
            if current in seen:
                issues.append(f"o[{start}] 父级形成环")
                break
            seen.add(current)
            next_parent = parents[current - 1]
            if not isinstance(next_parent, int):
                break
            current = next_parent
    return issues


def _review_rows(payload: dict[str, Any], observations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    rows = payload.get("reviews")
    if not isinstance(rows, list):
        return [], ["独立复核未返回 reviews 数组"]
    expected = {(row["object_index"], row["field_id"]) for row in observations}
    seen: set[tuple[int, str]] = set()
    valid: list[dict[str, Any]] = []
    issues: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            issues.append("复核项不是对象")
            continue
        key = (row.get("object_index"), row.get("field_id"))
        if (
            not isinstance(key[0], int) or isinstance(key[0], bool)
            or not isinstance(key[1], str)
            or key not in expected or key in seen
            or row.get("verdict") not in {"supported", "contradicted", "unknown"}
        ):
            issues.append(f"复核项无效或重复：{key}")
            continue
        seen.add(key)
        reason = str(row.get("reason") or "")[:500]
        if row["verdict"] == "supported" and not reason.strip():
            issues.append(f"复核支持缺少视觉理由：{key}")
            continue
        valid.append({
            "object_index": key[0], "field_id": key[1], "verdict": row["verdict"],
            "reason": reason,
        })
    if seen != expected:
        issues.append(f"独立复核缺少 {len(expected - seen)} 项观察")
    return valid, issues


def _invoke(agent: Any, text: str, image_data: str, content_type: str, telemetry: ModelCallTelemetry) -> str:
    result = agent.invoke(
        {"messages": [HumanMessage(content=[
            {"type": "text", "text": text},
            {"type": "image", "base64": image_data, "mime_type": content_type},
        ])]},
        config={"recursion_limit": 40, "callbacks": [telemetry]},
    )
    if not isinstance(result, dict):
        raise ValueError("DeepAgent 返回结构不合法")
    return _reply(result)


def run_prism_v2_extraction(
    *, image_path: Path, content_type: str, model_id: str, user_prompt: str,
    progress_callback: Any = None, source_record: dict[str, Any] | None = None,
) -> PrismOutput:
    """每张图各建主提取与独立复核；保留失败的结构候选供人工查看。"""

    def progress(stage: ExtractionStage, message: str, percent: int, level=ProgressEventLevel.INFO):
        if progress_callback:
            progress_callback(stage, message, percent, level)

    started = datetime.now(UTC)
    timer = monotonic()
    image_bytes = image_path.read_bytes()
    image_data = base64.b64encode(image_bytes).decode("ascii")
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    metadata_path = image_path.parent / "metadata.json"
    source_metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.is_file() else None
    )
    primary_telemetry = ModelCallTelemetry()
    review_telemetry = ModelCallTelemetry()
    progress(ExtractionStage.MODEL_ANALYSIS, "D02 R17 主提取正在分析原图", 12)
    primary_raw = _invoke(
        create_primary_agent(model_id),
        "只分析附图。原图 SHA256：" + image_hash + "。用户关注点：" + (user_prompt.strip() or "无"),
        image_data, content_type, primary_telemetry,
    )
    progress(ExtractionStage.PARSING, "解析 R17 编码并执行冻结 Schema 校验", 55)
    issues: list[str] = []
    candidate: dict[str, Any] | None = None
    try:
        candidate = _parse_json(primary_raw)
    except (ValueError, json.JSONDecodeError) as exc:
        issues.append(f"JSON 解析失败：{exc}")
    if candidate is not None:
        issues.extend(
            f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
            for error in sorted(_validator().iter_errors(candidate), key=lambda item: str(item.absolute_path))[:100]
        )
    schema_valid = candidate is not None and not issues
    protocol_issues = _protocol_issues(candidate) if schema_valid and candidate is not None else []
    protocol_valid = schema_valid and not protocol_issues
    observations = _observations(candidate) if protocol_valid and candidate is not None else []
    review_raw: str | None = None
    reviews: list[dict[str, Any]] = []
    review_issues: list[str] = []
    if observations and len(observations) <= MAX_REVIEW_OBSERVATIONS:
        progress(ExtractionStage.SEMANTIC_REVIEW, "独立 Agent 复核同一原图的局部 CMF", 70)
        try:
            review_raw = _invoke(
                create_review_agent(model_id),
                "请逐条复核以下候选观察；对象索引从 0 起，geometry 为 R17 原坐标。\n"
                + json.dumps(observations, ensure_ascii=False, separators=(",", ":")),
                image_data, content_type, review_telemetry,
            )
            reviews, review_issues = _review_rows(_parse_json(review_raw), observations)
        except Exception as exc:  # 复核故障不丢弃已完成的主提取原始回复。
            review_issues = [f"独立复核失败：{exc}"]
    elif len(observations) > MAX_REVIEW_OBSERVATIONS:
        review_issues.append(f"待复核项超过 {MAX_REVIEW_OBSERVATIONS} 项，尚未执行完整复核")
    elif not protocol_valid:
        review_issues.append("结构未通过 R41 Schema 或基础关系校验，跳过局部 CMF 复核")
    review_complete = bool(observations) and not review_issues
    result_id = uuid4().hex
    finished = datetime.now(UTC)
    payload = {
        "id": result_id,
        "skill": SKILL_NAME,
        "schema_version": "prism_d02_candidate_v1",
        "image_name": image_path.name,
        "created_at": finished.isoformat(),
        "source": {
            "image_id": image_path.parent.name, "image_sha256": image_hash,
            "image_filename": image_path.name, "content_type": content_type,
            "upload_metadata": source_metadata,
            "upload_metadata_sha256": _sha(metadata_path) if metadata_path.is_file() else None,
            "research": source_record,
        },
        "execution": {
            "model_id": model_id, "user_prompt": user_prompt, "started_at": started.isoformat(),
            "finished_at": finished.isoformat(), "duration_seconds": round(monotonic() - timer, 3),
            "prompt_version": PROMPT_VERSION, "prompt_sha256": _sha(PROMPT_PATH),
            "schema_sha256": _sha(SCHEMA_PATH), "skill_sha256": _sha(SKILL_ROOT / "SKILL.md"),
            "review_version": REVIEW_VERSION,
            "primary_usage": primary_telemetry.snapshot(), "review_usage": review_telemetry.snapshot(),
        },
        "validation": {
            "r41_schema_valid": schema_valid, "schema_issues": issues,
            "basic_protocol_valid": protocol_valid, "protocol_issues": protocol_issues,
            "review_complete": review_complete, "review_issues": review_issues,
            "official_projection_verified": False,
            "note": "可选模型候选结果；未运行冻结环境的完整编码/语义验收和官方 verify_projection。",
        },
        "observations": observations,
        "reviews": reviews,
        "candidate": candidate,
        "raw_responses": {"primary": primary_raw, "review": review_raw},
    }
    progress(ExtractionStage.FINALIZING, "保存候选结果、复核记录与来源哈希", 95)
    result_dir = _result_dir_for_source(source_record)
    path = result_dir / f"{result_id}.json"
    preview = _preview_path(result_dir, result_id)
    try:
        if result_dir == LIKED_IMAGES_RESULT_DIR:
            save_result_image(result_id, image_path, output_dir=preview.parent)
        else:
            save_result_image(result_id, image_path)
        _atomic_write(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except Exception:
        preview.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise
    return PrismOutput(result_id)


def reuse_prism_result(
    result_id: str, *, image_path: Path, source_record: dict[str, Any]
) -> PrismOutput:
    """原图哈希相同则复用模型输出，同时给另一条用研图片保留独立来源与展示项。"""

    original = load_prism_result(result_id)
    if original["source"]["image_sha256"] != _sha(image_path):
        raise ValueError("原图哈希不同，不能复用 D02 提取")
    copied = json.loads(json.dumps(original, ensure_ascii=False))
    new_id = uuid4().hex
    copied["id"] = new_id
    copied["image_name"] = image_path.name
    copied["created_at"] = datetime.now(UTC).isoformat()
    copied["source"].update({
        "image_id": image_path.parent.name,
        "image_filename": image_path.name,
        "upload_metadata": None,
        "upload_metadata_sha256": None,
        "research": source_record,
    })
    copied["execution"]["reused_from_result_id"] = result_id
    result_dir = _result_dir_for_source(source_record)
    path = result_dir / f"{new_id}.json"
    preview = _preview_path(result_dir, new_id)
    try:
        if result_dir == LIKED_IMAGES_RESULT_DIR:
            save_result_image(new_id, image_path, output_dir=preview.parent)
        else:
            save_result_image(new_id, image_path)
        _atomic_write(path, (json.dumps(copied, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except Exception:
        preview.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise
    return PrismOutput(new_id)


def _result_dir_for_source(source_record: dict[str, Any] | None) -> Path:
    """按冻结批次身份落盘，避免普通 D02 结果被误标为用户喜欢图片。"""

    return LIKED_IMAGES_RESULT_DIR if (source_record or {}).get("batch_id") == PPT_ENJOY_BATCH_ID else RESULT_DIR


def _preview_path(result_dir: Path, result_id: str) -> Path:
    image_dir = LIKED_IMAGES_PREVIEW_DIR if result_dir == LIKED_IMAGES_RESULT_DIR else RESULTS_DIR / ".images"
    return image_dir / f"{result_id}.webp"


def prism_result_path(result_id: str) -> Path:
    """定位用户喜欢图片或普通 D02 的单图结果，供读取与删除共用。"""

    if not RESULT_ID.fullmatch(result_id):
        raise FileNotFoundError("D02 结果不存在")
    for result_dir in (LIKED_IMAGES_RESULT_DIR, RESULT_DIR):
        path = result_dir / f"{result_id}.json"
        if path.is_file():
            return path
    raise FileNotFoundError("D02 结果不存在")


def prism_result_image_path(result_id: str) -> Path:
    """缩略图跟随结果所属目录，页面 URL 无需因数据迁移而变化。"""

    return _preview_path(prism_result_path(result_id).parent, result_id)


def load_prism_result(result_id: str) -> dict[str, Any]:
    return json.loads(prism_result_path(result_id).read_text(encoding="utf-8"))


def list_prism_results() -> list[dict[str, Any]]:
    results = []
    seen: set[str] = set()
    for path in (*LIKED_IMAGES_RESULT_DIR.glob("*.json"), *RESULT_DIR.glob("*.json")):
        if path.stem in seen:
            continue
        try:
            data = load_prism_result(path.stem)
        except (OSError, ValueError):
            continue
        seen.add(path.stem)
        is_r5 = data.get("schema_version") == "prism_sol_r5_candidate_v1"
        validation = data.get("validation") or {}
        results.append({
            "id": data["id"], "image_name": data["image_name"],
            "created_at": data["created_at"], "model_id": data["execution"]["model_id"],
            "schema_version": data.get("schema_version"),
            "preview_url": f"/api/v1/dna-v2/results/{data['id']}/image",
            "schema_valid": validation.get("primary_schema_valid") if is_r5 else validation.get("r41_schema_valid"),
            "review_complete": validation.get("focus_complete") if is_r5 else validation.get("review_complete"),
            "object_count": len((data.get("candidate") or {}).get("o", [])) if not is_r5 else 0,
            "feature_count": len((data.get("r5_result") or {}).get("features", [])) if is_r5 else 0,
            "research": data.get("source", {}).get("research"),
        })
    return sorted(results, key=lambda item: item["created_at"], reverse=True)


def read_ppt_enjoy_batch() -> dict[str, Any]:
    """供 V2 页面展示冻结范围、进度及逐图失败，不触发模型调用。"""

    if not PPT_ENJOY_BATCH_MANIFEST.is_file():
        raise FileNotFoundError("PPT ENJOY 批次尚未创建")
    manifest = json.loads(PPT_ENJOY_BATCH_MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["entries"]
    validations: dict[str, dict[str, Any]] = {}
    for entry in entries:
        result_id = entry.get("result_id")
        if not result_id:
            continue
        try:
            validations[result_id] = load_prism_result(result_id)["validation"]
        except (FileNotFoundError, OSError, ValueError, KeyError):
            continue
    return {
        "batch_id": manifest["batch_id"], "status": manifest["status"],
        "model_id": manifest["model_id"], "total_paths": manifest["total_paths"],
        "unique_image_sha256": manifest["unique_image_sha256"],
        "max_concurrency": manifest["max_concurrency"],
        "updated_at": manifest["updated_at"],
        "stopped_reason": manifest.get("stopped_reason"),
        "counts": {key: sum(entry["status"] == key for entry in entries) for key in ("pending", "running", "completed", "failed")},
        "quality_counts": {
            "schema_valid": sum(bool(v.get("r41_schema_valid")) for v in validations.values()),
            "protocol_valid": sum(bool(v.get("basic_protocol_valid")) for v in validations.values()),
            "review_complete": sum(bool(v.get("review_complete")) for v in validations.values()),
        },
        "entries": [{
            "source_path": entry["source_path"], "status": entry["status"],
            "result_id": entry["result_id"], "error": entry["error"],
            "duration_seconds": entry["duration_seconds"],
            "reused_from_result_id": entry["reused_from_result_id"],
            "schema_valid": validations.get(entry.get("result_id"), {}).get("r41_schema_valid"),
            "protocol_valid": validations.get(entry.get("result_id"), {}).get("basic_protocol_valid"),
            "review_complete": validations.get(entry.get("result_id"), {}).get("review_complete"),
            "user_names": sorted({pref["user_name"] for pref in entry["preferences"]}),
            "ref_pic_codes": sorted({str(pref["ref_pic_code"]) for pref in entry["preferences"] if pref.get("ref_pic_code")}),
        } for entry in entries],
    }

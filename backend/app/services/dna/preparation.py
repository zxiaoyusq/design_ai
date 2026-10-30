"""设计卡网页适配；历史冻结卡只读，新请求用工程 DeepAgents 后交给原生冻结。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache, partial
import importlib.util
import json
import mimetypes
from pathlib import Path
import re
from threading import Lock
from typing import Any
from uuid import uuid4

from app.schemas.dna import ExtractionStage, ProgressEventLevel
from app.agents.bounded import AGENT_RUNTIME_VERSION
from app.agents.design_dna_preparation import DEFAULT_MODEL, TRANSPORT, execution_config, execute_structured
from app.services.dna.storage import PROJECT_ROOT, RESULTS_DIR, _atomic_write
from app.services.llm.catalog import get_model, list_models


SKILL_NAME = "prism-design-dna-preparation"
SKILL_ROOT = PROJECT_ROOT / ".agents/skills" / SKILL_NAME
FROZEN_MANIFEST = PROJECT_ROOT / "data/result/dna_cluster_moodboard/sample1600_balanced_llm_20261010/preparation/prepared-manifest.json"
WEB_ROOT = RESULTS_DIR / "dna_preparation_web"
SCHEMA_VERSION = "prism_prepared_design_cards_v1"
MODEL, EFFORT = "gpt-6.1-sol", "high"  # 仅为只读 1600 图历史快照身份。
RESULT_ID = re.compile(r"^(?:prep1600-[\w-]+|prep-[a-f0-9]{32})$")
_snapshot_lock = Lock()


@dataclass(frozen=True)
class PreparationOutput:
    result_id: str


class PreparationExecutionError(RuntimeError):
    """保留原生停发信号供批量调用方使用；单图调用方仍可按 RuntimeError 处理。"""

    def __init__(self, message: str, *, result_id: str, stop_new_calls: bool):
        super().__init__(message)
        self.result_id = result_id
        self.stop_new_calls = stop_new_calls


@lru_cache(maxsize=1)
def native():
    """直接加载 Skill 原生校验和版本声明，网页不复制七组关系与风格规则。"""
    path = SKILL_ROOT / "scripts/design_cards.py"
    spec = importlib.util.spec_from_file_location("prism_web_design_cards", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("设计 DNA 预提取 Skill 不可读取")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def _fingerprint(path: Path) -> tuple[str, int, int]:
    info = path.stat()
    return str(path.resolve()), info.st_mtime_ns, info.st_size


@lru_cache(maxsize=8)
def _snapshot(manifest_identity: tuple, cards_identity: tuple) -> dict:
    manifest, document, expected = native().prepared_header(Path(manifest_identity[0]))
    cards: dict[str, list[dict]] = defaultdict(list)
    for card in document["cards"]:
        cards[card["image_id"]].append(card)
    return {"manifest": manifest, "document": document, "expected": expected,
            "cards": cards, "ledger": {row["image_id"]: row for row in document["images"]}}


def _load_snapshot(path: Path) -> dict:
    # 冷加载包含冻结容器 SHA 核验，串行填缓存防止首页摘要和列表重复解析大文档。
    with _snapshot_lock:
        manifest = json.loads(path.read_bytes())
        return _snapshot(_fingerprint(path), _fingerprint(Path(manifest["design_cards_ref"]["path"])))


def _base() -> dict:
    return _load_snapshot(FROZEN_MANIFEST)


def _web_contexts() -> tuple[list[tuple[dict, str, dict]], list[dict]]:
    """隔离新运行的损坏索引，避免单次写盘故障令已冻结 1600 图全部不可访问。"""
    contexts, unavailable = [], []
    for path in (WEB_ROOT / "results").glob("prep-*.json"):
        try:
            record = json.loads(path.read_bytes())
            if (not isinstance(record, dict) or record.get("id") != path.stem or record.get("schema_version") != SCHEMA_VERSION
                    or not re.fullmatch(r"prep-[a-f0-9]{32}", path.stem)):
                raise ValueError("新结果索引身份无效")
            contexts.append(_result_context(record["id"]))
        except (OSError, ValueError, KeyError, TypeError):
            unavailable.append({"id": path.stem, "error": "该次新提取的冻结记录不可读取或校验失败"})
    return contexts, unavailable


def _result_context(result_id: str) -> tuple[dict, str, dict | None]:
    if not RESULT_ID.fullmatch(result_id):
        raise FileNotFoundError("设计 DNA 预提取结果不存在")
    if result_id.startswith("prep1600-"):
        snapshot, image_id, record = _base(), result_id.removeprefix("prep1600-"), None
    else:
        path = WEB_ROOT / "results" / f"{result_id}.json"
        if not path.is_file():
            raise FileNotFoundError("设计 DNA 预提取结果不存在")
        record = json.loads(path.read_bytes())
        if not isinstance(record, dict) or record.get("id") != result_id or record.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("设计 DNA 结果索引身份不一致")
        manifest = WEB_ROOT / "runs" / result_id / "preparation/prepared-manifest.json"
        if record.get("manifest_ref") != native().reference(manifest):
            raise ValueError("设计 DNA 运行清单引用不一致")
        snapshot, image_id = _load_snapshot(manifest), record["image_id"]
    if image_id not in snapshot["expected"]:
        raise FileNotFoundError("设计 DNA 预提取结果不存在")
    return snapshot, image_id, record


def _summary(snapshot: dict, image_id: str, result_id: str, record: dict | None = None) -> dict:
    row, ledger = snapshot["expected"][image_id], snapshot["ledger"][image_id]
    cards = snapshot["cards"].get(image_id, [])
    style_names = {item["style_id"]: item["name"] for item in snapshot["document"]["style_catalog"]}
    styles = sorted({candidate["style_id"] for card in cards for candidate in card["style_candidates"]})
    created = max((card["provenance"]["assessed_at"] for card in cards), default=snapshot["document"]["created_at"])
    model_id, effort = MODEL, EFFORT
    if record is not None:
        plan = native().read_ref(snapshot["document"]["plan_ref"])
        model_id, effort = plan["model"], plan["reasoning_effort"]
    return {"id": result_id, "image_name": (record or {}).get("image_name", Path(row["local_path"]).name),
            "image_id": image_id, "image_sha256": row["sha256"], "created_at": created, "model_id": model_id, "reasoning_effort": effort,
            "schema_version": SCHEMA_VERSION, "preview_url": f"/api/v1/dna-v2/results/{result_id}/image",
            "status": "partial" if cards and ledger.get("errors") else ledger["status"],
            "schema_valid": bool(cards), "review_complete": False,
            "object_count": len(cards), "card_count": len(cards), "feature_count": len(cards) * 7,
            "branches": sorted({card["branch"] for card in cards}),
            "object_names": sorted({card["subject"]["identity"] for card in cards}),
            "category": "、".join(sorted({card["category"] for card in cards})),
            "style_candidates": styles, "style_ids": styles, "style_names": [style_names[key] for key in styles],
            "source_kind": row.get("source_kind", "unknown"),
            "prompt_versions": sorted({card["provenance"]["prompt_version"] for card in cards}),
            "frozen": True, "errors": ledger.get("errors", [])}


def list_prepared_results(*, query: str = "", branch: str | None = None) -> list[dict]:
    """一图一条，包含无有效卡的终态；只合并本 Skill 快照，不混入旧 R5 列表。"""
    snapshot = _base()
    results = [_summary(snapshot, image_id, "prep1600-" + image_id) for image_id in snapshot["expected"]]
    contexts, _ = _web_contexts()
    for current, image_id, record in contexts:
        results.append(_summary(current, image_id, record["id"], record))
    # 同一原图再次经用户确认提取时，默认图库只显示最新快照；旧详情与冻结证据仍保留。
    results = list({row["image_sha256"]: row for row in sorted(results, key=lambda row: row["created_at"])}.values())
    if branch:
        results = [row for row in results if branch in row["branches"]]
    if query.strip():
        text = query.strip().casefold()
        results = [row for row in results if text in json.dumps(row, ensure_ascii=False).casefold()]
    return sorted(results, key=lambda row: (row["card_count"] > 0, row["created_at"], row["id"]), reverse=True)


def preparation_overview() -> dict:
    snapshot = _base()
    document = snapshot["document"]
    contexts, unavailable = _web_contexts()
    return {"skill": SKILL_NAME, "schema_version": SCHEMA_VERSION,
            "snapshot_id": "sample1600_balanced_llm_20261010", "counts": document["counts"],
            "created_at": document["created_at"], "coverage_limit": document["coverage_limit"],
            "style_catalog": document["style_catalog"], "model_id": DEFAULT_MODEL, "reasoning_effort": None,
            "default_model": DEFAULT_MODEL,
            "available_models": [{"id": model.id, "name": model.name, "model_provider": model.model_provider.value} for model in list_models()],
            "transport": TRANSPORT, "framework": "DeepAgents", "agent_runtime_version": AGENT_RUNTIME_VERSION,
            "historical_model_id": MODEL, "historical_reasoning_effort": EFFORT,
            "prompt_versions": sorted({card["provenance"]["prompt_version"] for card in document["cards"]}),
            "current_prompt_version": native().PROMPT_VERSION,
            "new_extractions": len(contexts), "unavailable_new_results": unavailable, "automatic_retries": False,
            "historical_snapshot_read_only": True, "human_approved": False, "visual_accuracy_claimed": False}


def load_prepared_result(result_id: str) -> dict:
    snapshot, image_id, record = _result_context(result_id)
    cards, row = snapshot["cards"].get(image_id, []), snapshot["expected"][image_id]
    # 只验证用户打开的对象；原生校验绑定原答 pointer、回执、实际 Prompt 和原图 SHA。
    native().validate_frozen_cards(cards, snapshot["expected"], snapshot["document"])
    ledger, document = snapshot["ledger"][image_id], snapshot["document"]
    plan = native().read_ref(document["plan_ref"])
    summary = _summary(snapshot, image_id, result_id, record)
    receipt_ref = ledger.get("receipt_ref")
    if not receipt_ref:
        # 原生传输失败的图片台账没有回执字段；以冻结批次与实际调用账本关联，不猜路径。
        batch_id = next((batch["batch_id"] for batch in plan["batches"] if image_id in batch["image_ids"]), None)
        receipt_ref = next((call.get("receipt_ref") for call in document["execution"]["calls"]
                            if call["batch_id"] == batch_id), None)
    receipt = native().read_ref(receipt_ref) if receipt_ref else {}
    answer_ref = ledger.get("answer_ref") or receipt.get("answer_ref")
    if answer_ref:
        native().read_ref(answer_ref)
    # 无卡终态也核对原图和失败回执，不把“未选择对象／超时”包装为逐卡视觉通过。
    _verify_image(_fingerprint(Path(row["local_path"])), row["sha256"])
    return {**summary, "skill": SKILL_NAME, "cards": cards, "style_catalog": document["style_catalog"],
            "source": {"image_id": image_id, "image_sha256": row["sha256"],
                       "image_filename": summary["image_name"], "source_kind": row.get("source_kind", "unknown"),
                       "sources": row.get("sources", []), "image_url": row.get("image_url")},
            "execution": {"model_id": plan["model"], "reasoning_effort": plan["reasoning_effort"],
                          "prompt_version": plan["prompt_version"], "automatic_retries": False,
                          "actual_model": receipt.get("actual_model"),
                          "started_at": receipt.get("started_at", summary["created_at"]),
                          "finished_at": receipt.get("finished_at", document["created_at"]),
                          "adapter": receipt.get("model_adapter", "native_design_cards"),
                          "framework": receipt.get("framework", "DeepAgents"),
                          "transport": receipt.get("transport", "Codex CLI"), "usage": receipt.get("usage"),
                          "agent_runtime_version": receipt.get("agent_runtime_version"),
                          "new_model_calls_for_read": 0, "current_prompt_version": native().PROMPT_VERSION},
            "validation": {"native_evidence_verified": bool(cards), "container_verified": True,
                           "image_sha256_verified": True, "receipt_sha256_verified": bool(receipt), "status": ledger["status"],
                           "valid_card_count": len(cards), "human_approved": False,
                           "visual_board_approved": False, "visual_accuracy_claimed": False},
            "invalid_objects": ledger.get("errors", []), "image_record": ledger,
            "lineage": {"manifest": snapshot["manifest"].get("schema_version"),
                        "design_cards_ref": snapshot["manifest"]["design_cards_ref"],
                        "sample_ref": document["sample_ref"], "prior_observations_ref": document["prior_observations_ref"],
                        "plan_ref": document["plan_ref"], "receipt_ref": receipt_ref,
                        "answer_ref": answer_ref, "legacy_r5_modified": False},
            "coverage_limit": document["coverage_limit"]}


@lru_cache(maxsize=4096)
def _verify_image(identity: tuple, expected_sha: str) -> None:
    if native().digest(identity[0]) != expected_sha:
        raise ValueError("原图 SHA 与冻结结果不一致")


def prepared_image_path(result_id: str) -> tuple[Path, str]:
    """图片路径完全来自冻结白名单，并限制在项目 data 内；不接受客户端文件路径。"""
    snapshot, image_id, _ = _result_context(result_id)
    row = snapshot["expected"][image_id]
    path = Path(row["local_path"]).resolve(strict=True)
    if not path.is_relative_to((PROJECT_ROOT / "data").resolve()):
        raise ValueError("冻结图片不在项目数据目录")
    _verify_image(_fingerprint(path), row["sha256"])
    return path, mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def validate_preparation_request(model_id: str, user_prompt: str) -> None:
    get_model(model_id)
    if user_prompt.strip():
        raise ValueError("设计 DNA 预提取使用 Skill 原生提示，不接受附加关注点")


def _prior_for_upload(image_hash: str) -> tuple[dict | None, dict]:
    """只从指定快照复用同字节 R5 和旧观察，不扫描其他运行或重写旧事实。"""
    snapshot = _base()
    matching = next((row for row in snapshot["expected"].values() if row["sha256"] == image_hash), None)
    if matching:
        prior = native().read_ref(snapshot["document"]["prior_observations_ref"])
        units = [row for row in prior.get("units", []) if row.get("image_id") == matching["image_id"]]
        return matching, {"schema_version": "prism.web_prior_observations.v1", "units": units}
    return None, {"schema_version": "prism.web_prior_observations.v1", "units": []}


def _stop_new_calls_after_failure(run_dir: Path, error: Exception) -> bool:
    """通用“无卡”包装不能吞掉原生额度/鉴权停发信号；只查本次运行的真实台账。"""
    output = run_dir / "preparation"
    for path in (output / "batch-results").glob("*.json"):
        try:
            report = json.loads(path.read_bytes()).get("report", {})
        except (OSError, ValueError, AttributeError):
            continue  # 损坏台账不是成功，也不能掩盖原始异常；继续查实际回执。
        if isinstance(report, dict) and (report.get("stop_new_calls") is True or report.get("previous_fatal_failure") is True):
            return True
    # 写批次报告前中断时仍可能已有真实失败回执，沿用 Skill 的分类而不维护第二套关键词。
    folders = [run_dir, output, *(output / "model-calls").glob("*")]
    for folder in folders:
        if folder.is_dir():
            try:
                if native().fatal_call_failure(folder, str(error)):
                    return True
            except OSError:
                continue
    return False


def run_preparation_extraction(*, image_path: Path, content_type: str, model_id: str,
                               user_prompt: str, progress_callback: Any = None) -> PreparationOutput:
    """网页确认的单图经工程 DeepAgents 执行一次 A 阶段，再由 Skill 原生冻结。"""
    validate_preparation_request(model_id, user_prompt)
    configuration = execution_config(model_id)
    source_path = image_path.resolve(strict=True)
    result_id = "prep-" + uuid4().hex
    run_dir = WEB_ROOT / "runs" / result_id
    image_hash = native().digest(source_path)
    previous, prior = _prior_for_upload(image_hash)
    image_id = previous["image_id"] if previous else image_hash[:32]
    # 同字节独立归档，删除上传素材不会破坏冻结卡对应的原图证据。
    image_copy = run_dir / ("original" + source_path.suffix.lower())
    _atomic_write(image_copy, source_path.read_bytes())
    row = {"image_id": image_id, "sha256": image_hash, "local_path": str(image_copy.resolve()),
           "source_kind": (previous or {}).get("source_kind", "upload"), "sources": (previous or {}).get("sources", [])}
    if previous and previous.get("dna_primary_ref"):
        row["dna_primary_ref"] = previous["dna_primary_ref"]
    sample_path, prior_path = run_dir / "sample.json", run_dir / "prior-observations.json"
    _write(sample_path, {"schema_version": "prism.web_design_cards_sample.v1", "images": [row]})
    _write(prior_path, prior)
    if progress_callback:
        progress_callback(ExtractionStage.MODEL_ANALYSIS, "按设计 DNA 预提取 Skill 识别对象、七组关系及风格依据", 15, ProgressEventLevel.INFO)
    try:
        _write(run_dir / "web-invocation.json", {"framework": "DeepAgents", "transport": TRANSPORT,
               "execution_config": configuration, "model_id": model_id,
               "reasoning_effort": configuration["reasoning_effort"], "automatic_retries": False,
               "content_type": content_type, "source_image_name": source_path.name})
        native().run(sample_path, prior_path, run_dir / "preparation", batch_size=1, workers=1, execute=True,
                     executor=partial(execute_structured, model_id=model_id), execution_config=configuration)
        manifest_path = run_dir / "preparation/prepared-manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("原生 Skill 未产生冻结清单；保留失败记录，不自动重试")
        snapshot = _load_snapshot(manifest_path)
        if set(snapshot["expected"]) != {image_id} or snapshot["expected"][image_id]["sha256"] != image_hash:
            raise ValueError("原生 Skill 输出不属于本次上传图片")
        cards = snapshot["cards"].get(image_id, [])
        native().validate_frozen_cards(cards, snapshot["expected"], snapshot["document"])
        record = {"id": result_id, "schema_version": SCHEMA_VERSION, "image_id": image_id,
                  "image_name": source_path.name, "manifest_ref": native().reference(manifest_path)}
        _write(WEB_ROOT / "results" / f"{result_id}.json", record)
        if not cards:
            raise RuntimeError("本图未产生有效设计卡；失败原因已登记到提取结果")
        return PreparationOutput(result_id)
    except Exception as exc:
        stop_new_calls = _stop_new_calls_after_failure(run_dir, exc)
        _write(run_dir / "web-failure.json", {"result_id": result_id, "failed_at": datetime.now(UTC).isoformat(),
               "error": f"{type(exc).__name__}: {str(exc)[:500]}", "stop_new_calls": stop_new_calls})
        raise PreparationExecutionError(f"设计 DNA 预提取失败；运行记录 {result_id}：{str(exc)[:500]}",
                                        result_id=result_id, stop_new_calls=stop_new_calls) from exc

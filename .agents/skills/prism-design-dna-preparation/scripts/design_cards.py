"""逐图补充关系型设计卡并冻结；旧 R5 不改写，模型调用显式授权且无自动重试。"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from time import monotonic

import jsonschema


VERSION = "prism.design_cards.v1"
PREPARED_VERSION = "prism.design_cards_prepared.v1"
PROMPT_VERSION = "prism-relational-design-cards-20261010-v2"
REPO = Path(__file__).resolve().parents[4]
CLUSTER = REPO / ".agents/skills/prism-dna-cluster-moodboard"
REFERENCE = REPO / "ref/multimodal-design-dna-multitag-extractor/references"
POLICY = Path(__file__).resolve().parents[1] / "references/relational-design-policy.md"
MODEL, EFFORT = "gpt-6.1-sol", "high"
RELATIONS = ("palette", "silhouette", "planes", "lines", "optics", "texture", "details")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path: str | Path) -> dict:
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def read_ref(value: dict) -> object:
    path = Path(value["path"])
    if not path.is_absolute() or digest(path) != value["sha256"]:
        raise ValueError(f"引用 SHA 不一致或非绝对路径：{path}")
    return json.loads(path.read_bytes())


def write_new(path: Path, value: object) -> None:
    """新记录通过同目录临时文件原子发布，崩溃不留下半个 JSON。"""
    atomic_json(path, value, replace=False)


def atomic_json(path: Path, value: object, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # 已存在即失败，不覆盖原答或已完成批次。
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def execution_lock(out: Path):
    """同一运行目录只能有一个调度器，进程退出时文件锁自动释放。"""
    with (out / ".execution.lock").open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("当前输出目录仍有运行中的提取调度器，禁止并行 resume") from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def object_schema(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def strings(minimum: int = 0) -> dict:
    return {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": minimum}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


def style_catalog() -> tuple[list[dict], list[dict]]:
    """只机械摘录可见机制；不把旧知识库的 confirmed 硬门槛带入 v3 同层候选协议。"""
    registry_path, knowledge_path = REFERENCE / "style-registry.json", REFERENCE / "design-dna-knowledge-base.zh-CN.md"
    registry = json.loads(registry_path.read_bytes())
    active = [item for item in registry["styles"] if item.get("status") == "active"]
    knowledge = knowledge_path.read_text()
    sections = dict(re.findall(r"^### ([A-Za-z0-9]+) — [^\n]+\n(.*?)(?=^### |^# |\Z)", knowledge, re.M | re.S))
    catalog = []
    for item in active:
        fields = dict(re.findall(r"^\| ([^|]+?) \| ([^|]+?) \|$", sections[item["style_id"]], re.M))
        catalog.append({"style_id": item["style_id"], "name": item["display_name_zh"],
                        "visible_mechanism": fields["核心机制"], "visible_anchors": fields["决定锚点"],
                        "counter_signals": fields["硬排除"]})
    if len(catalog) != 38 or "TribeIdentity" in {item["style_id"] for item in catalog}:
        raise ValueError("活动风格表发生变化，需要重新审核协议，不静默迁移")
    return catalog, [reference(registry_path), reference(knowledge_path),
                     reference(REFERENCE / "extraction-protocol.zh-CN.md")]


def card_schema(style_ids: list[str]) -> dict:
    text = {"type": "string", "minLength": 1}
    bbox = {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 4, "maxItems": 4}
    relation = object_schema({"observation": text, "evidence": strings(), "unknown": {"type": "boolean"}})
    style = object_schema({"style_id": enum(*style_ids), "match_score": {"type": "number", "minimum": 0, "maximum": 100},
                           "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                           "main_support": strings(1), "main_conflicts": strings()})
    return object_schema({
        "branch": enum("ID", "CMF"),
        "subject": object_schema({"identity": text, "role": enum("primary_object", "peer_object"),
                                  "bbox": bbox, "whole_visible": {"type": "boolean"}}),
        "display_bbox": bbox, "evidence_bbox": bbox,
        "display_scope": enum("whole_object", "representative_detail"), "crop_reason": text, "category": text,
        "relations": object_schema({key: relation for key in RELATIONS}),
        "design_emotion": object_schema({"expression": text, "coordination_reason": text, "counter_signals": strings()}),
        "design_quality": object_schema({"level": enum("strong", "considered", "ordinary", "uncertain"), "evidence": strings()}),
        "style_candidates": {"type": "array", "items": style, "maxItems": 5},
        "limitations": strings(), "runway": enum("yes", "no", "unknown"),
    })


def response_schema(image_ids: list[str], style_ids: list[str]) -> dict:
    return object_schema({"images": {"type": "array", "items": object_schema({
        "image_id": enum(*image_ids), "limitations": strings(), "cards": {"type": "array", "maxItems": 3,
                                                                            "items": card_schema(style_ids)}}),
        "minItems": len(image_ids), "maxItems": len(image_ids)}})


SYSTEM = """你执行独立的逐图设计 DNA 补缺，不做多图比较、聚类、命名情绪板或审美批准。
旧 R5 和旧观察只是待原图核对的上下文，不是新证据；不要重提全套规范字典。对每图最多 1 个 ID、2 个 CMF 对象/取景生成关系型设计卡，可为零；此限额不代表已穷尽所有对象。
只选主物品或同级、有独立设计表达的物品，不能选背景墙角、偶然小色块。图中建筑、房间或空间本身可以是被呈现的设计对象，但房间里无关小墙角不是自动合格对象。ID、CMF 均可整体或代表性局部；局部必须具有该对象代表性的设计关系并保留归属，不能因相似方便而选碎角。
所有 bbox 都是原图归一化 [x,y,width,height]，绝不是 xyxy；subject.bbox 是可见对象包围框，evidence_bbox 是事实位置，display_bbox 是真实展示窗。事实框必须在对象框和展示框内；展示框可以稍含上下文。whole_object 必须原图确实看得见整物且展示框包含整对象；画外有截断就用 representative_detail 并如实声明，不假装整物。不得把裁框边缘当产品轮廓。
先观察关系，再概括风格和设计情绪。两分支都写对象可见整体配色、轮廓、块面、线条组织；局部卡的 relations 要明确区分整对象上下文与局部证据。画外的整物关系 unknown，不从局部外推。CMF 再细看真实表面的光学与纹理。
先说明当前对象和 display_bbox 内最显著、持续主导阅读的表达，再记录次要或偶发细节；在相关 observation 中说明主次及位置，不因一点圆角、细边、同色或平滑局部把主导的厚重、卷曲交叠、强纹理等概括为相反表达。不预设简洁、低彩度或柔和比其他表达更好。
对象自身事实与当前 display_bbox 内的竞争信息分别记录。背景陈设、光晕、文字、邻近物等不是对象配色或材质；但它们若仍在展示窗内并影响主导阅读，在 design_emotion.counter_signals 写出其位置、视觉作用及归属，在 limitations 说明遮挡、归属或可读性限制，必要时在相关 observation 区分对象与视窗上下文。不能因不属于对象就忽略其显示影响，也不能借给对象表面；明确对象自身的文字或装饰应正常记录。可见色面不能仅因归属不明就当成阴影，归属未明时保留未知；没有可见干扰则不强造反向信号。
同图 ID/CMF 观察仅在确属同一对象、证据适用于当前 display_bbox 且能从原图核实时互相参考；同图不代表同对象，不自动把空间全图、另一物品或框外信息串入当前局部卡。框外上下文须明确标出，不能作为当前展示窗中的直接支持或竞争信息。
palette 写主体主色、辅色、点缀色的相对视觉角色及明暗、彩度、对比和分区，不能拿背景颜色、滤镜或一点暖色覆盖大面积深色，不编面积百分比。
silhouette 写可见廓形、比例、转折、轮廓张力；planes 写块面/体量、分区、层级、负空间、大小节奏；lines 写直曲、方向、密度、间距、锐钝、连续性及线条是结构边界还是表面纹样。
服装也有结构：肩线、裁片、领袖、剪裁与褶裥能形成清楚的几何廓形、块面与线条。不得因材质柔软或品类为服装就判无结构；不用跨品类物理组件数量比较复杂度。
optics 写光泽、反射清晰度/方向、漫散/镜面、透光层次；texture 写载体、纹理单元、相对对象尺度、密度、路径、覆盖、抽象/具象、机械清晰/自然毛糙；宏观褶皱/构件阵列不等于微细纹理。details 写接缝/边缘/连接和细节语言。材料只写可见外观，真实成分、工艺、触感未知。
每项 relations={observation,evidence:[可见事实],unknown}，不知道不是没有，unknown=false 需要至少一条证据；证据必须具体可定位，尽量每维 1–2 句，不堆空泛同义词。
按原图与当前展示窗实际清晰度，在 limitations 具体区分可支持与不可支持的判断，例如能读廓形、色块和大面层级，但不能确认微纹理、窄接缝或精细边缘；低清、遮挡、强光照导致的限制要落实到相应关系。放大不能增加原有证据，模糊不能证明表面光滑或没有接缝；一个维度只能支持部分观察时保留已知事实并写清未知部分，不把整对象一概判为不可读。
设计情绪是形态、比例、色彩、质感、细节的组合感受，记录 coordination_reason 和反向信号，不能靠一个圆润/金属/颜色词推断。design_quality 记录控制比例、构成、细节与表达统一的可见理由，不按价格、品牌、摄影、材质高低排序。
风格仅借鉴多标签提取 v3.0.3 的同层候选机制，不宣称这是完整规范 192 字段提取。使用提供的 38 活动风格，0–5 项，每项需实际支持和反向信号；无 confirmed/主次/最低置信硬门槛。catalog 的反向信号用于报告冲突，不机械照搬旧版确认计数门。不得输出 TribeIdentity、组合预设，不让风格名字反向补事实。confidence 是模型自评非经校准概率，match_score 不是聚类距离。
runway 仅依据可见秀场场景或给定已核来源；衣服/有人不等于走秀，不确定用 unknown。只返回所需 JSON，不追加工具或解释。
"""


def validate_card(card: dict, style_ids: list[str]) -> None:
    """语义失败只排除当前卡，不把同图合法 CMF/ID 连带丢弃。"""
    jsonschema.Draft202012Validator(card_schema(style_ids)).validate(card)
    boxes = [card["subject"]["bbox"], card["display_bbox"], card["evidence_bbox"]]
    for x, y, width, height in boxes:
        if width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
            raise ValueError("无效的 normalized xywh 框")

    def contains(outer, inner):
        return all((outer[0] <= inner[0] + 1e-6, outer[1] <= inner[1] + 1e-6,
                    outer[0] + outer[2] + 1e-6 >= inner[0] + inner[2],
                    outer[1] + outer[3] + 1e-6 >= inner[1] + inner[3]))

    if not contains(boxes[0], boxes[2]) or not contains(boxes[1], boxes[2]):
        raise ValueError("事实框必须在对象框及展示框内")
    if card["display_scope"] == "whole_object" and (not card["subject"]["whole_visible"] or not contains(boxes[1], boxes[0])):
        raise ValueError("whole_object 不得用于原图不完整或被展示裁断的对象")
    for value in card["relations"].values():
        if not value["unknown"] and not value["evidence"]:
            raise ValueError("已知关系必须有可见证据")
    if card["design_quality"]["level"] != "uncertain" and not card["design_quality"]["evidence"]:
        raise ValueError("设计感判断缺少可见依据")
    ids = [item["style_id"] for item in card["style_candidates"]]
    if len(ids) != len(set(ids)):
        raise ValueError("风格候选重复")


def prior_context(image: dict, prior: dict) -> dict:
    fields = ("branch", "primary_subject", "target_role", "display_scope", "display_bbox", "evidence_bbox", "features",
              "evidence", "limitations", "whole_appearance", "design_emotion")
    old_units = [item for item in prior.get("units", []) if item.get("image_id") == image["image_id"]]
    if any(item.get("image_sha256") != image["sha256"] for item in old_units):
        raise ValueError("旧观察图像身份与当前样本不同")
    result = {"prior_units": [{key: item[key] for key in fields if key in item} for item in old_units],
              "prior_units_are_not_new_evidence": True, "old_bbox_format": "xywh_normalized"}
    dna_ref = image.get("dna_primary_ref")
    if dna_ref:
        original = read_ref(dna_ref)
        if not isinstance(original, dict):
            raise ValueError("旧 R5 顶层不是对象")
        # 历史 source 既可能是结构化对象，也可能只是图片路径字符串。
        source = original.get("source")
        source_sha = original.get("image_sha256") or (source.get("image_sha256") if isinstance(source, dict) else None)
        if source_sha and source_sha != image["sha256"]:
            raise ValueError("旧 R5 不属于当前原图")
        root = original.get("r5_result", original)
        prefix = "/r5_result" if "r5_result" in original else ""
        grouped = {}
        for index, fact in enumerate(root.get("local_features", [])):
            if str(fact.get("p", "")).startswith(("GEO-", "STR-", "COL-", "TEX-", "OPT-", "REL-")):
                grouped.setdefault((fact["p"].split("-")[0], str(fact.get("at"))), []).append(
                    {"p": fact["p"], "v": fact.get("v"), "at": fact.get("at"), "pointer": f"{prefix}/local_features/{index}"})
        selected = []
        while len(selected) < 24 and any(grouped.values()):
            for facts in grouped.values():
                if facts and len(selected) < 24:
                    selected.append(facts.pop(0))
        result["r5_context"] = {"source_ref": dna_ref, "facts": selected,
                                "full_original_in_model_context": False, "attached_fact_count": len(selected)}
    return result


def _execution_config(config: dict | None) -> dict:
    """默认保留历史 CLI 契约；工程适配器必须显式冻结自身模型及传输身份。"""
    if config is None:
        return {"model": MODEL, "reasoning_effort": EFFORT,
                "runtime_ref": reference(CLUSTER / "scripts/model_runtime.py"), "actual_model_policy": "exact"}
    required = {"model", "reasoning_effort", "runtime_ref", "transport", "actual_model_policy", "model_options", "configuration_refs"}
    if (set(config) != required or not isinstance(config["model"], str) or not config["model"]
            or config["reasoning_effort"] is not None and not isinstance(config["reasoning_effort"], str)
            or config["actual_model_policy"] not in {"exact", "provider_reported"}
            or config["transport"] != "project_langchain_sdk"):
        raise ValueError("工程执行配置必须明确绑定模型、推理配置、运行器和传输协议")
    if digest(config["runtime_ref"]["path"]) != config["runtime_ref"]["sha256"]:
        raise ValueError("工程运行器 SHA 不匹配")
    if any(digest(item["path"]) != item["sha256"] for item in config["configuration_refs"]):
        raise ValueError("工程模型配置或受限执行依赖 SHA 不匹配")
    return deepcopy(config)


def make_plan(sample_path: Path, prior_path: Path, batch_size: int, workers: int,
              reuse_prepared: list[Path] | None = None, *, execution_config: dict | None = None) -> tuple[dict, list[dict], dict]:
    if not 1 <= batch_size <= 5 or not 1 <= workers <= 10:
        raise ValueError("batch-size 须在 1–5，workers 须在 1–10；以当次授权范围为准")
    configuration = _execution_config(execution_config)
    sample, prior = json.loads(sample_path.read_bytes()), json.loads(prior_path.read_bytes())
    rows = sample["images"]
    if not rows or len({row["image_id"] for row in rows}) != len(rows) or len({row["sha256"] for row in rows}) != len(rows):
        raise ValueError("样本必须非空，且 image_id 与 SHA 各自唯一")
    if prior.get("schema_version") == VERSION:
        raise ValueError("已冻结新版卡请直接交 Stage B；此入口补旧观察，不隐式重做新版卡")
    catalog, catalog_refs = style_catalog()
    policy_text = POLICY.read_text()
    inputs, invalid, context_warnings = [], [], []
    for row in rows:
        try:
            if digest(row["local_path"]) != row["sha256"]:
                raise ValueError("原图 SHA 与样本不一致")
            try:
                old_context = prior_context(row, prior)
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
                # 旧 DNA 缺损不代表原图不可提取；隔离不可信上下文，原图仍只请求一次。
                warning = f"旧上下文不可复用，当前请求仅依据原图：{type(exc).__name__}: {exc}"
                context_warnings.append({"image_id": row["image_id"], "warning": warning})
                old_context = {"prior_units": [], "prior_units_are_not_new_evidence": True, "context_warning": warning}
            inputs.append({"image_id": row["image_id"], "image_sha256": row["sha256"], **old_context})
        except (ValueError, OSError, KeyError) as exc:
            invalid.append({"image_id": row["image_id"], "sha256": row["sha256"], "status": "failed", "errors": [str(exc)]})
    batches = []
    by_id = {row["image_id"]: row for row in rows}
    system = SYSTEM + "\n共享比较语义（本阶段只逐图记录，禁止开始聚类）：\n" + policy_text
    reuse, reused_cards, reused_ledger = find_reusable_images(
        reuse_prepared or [], inputs, by_id, system, catalog, execution_config=execution_config)
    reused_ids = {row["image_id"] for row in reused_ledger}
    inputs = [row for row in inputs if row["image_id"] not in reused_ids]
    for start in range(0, len(inputs), batch_size):
        batch = inputs[start:start + batch_size]
        payload = {"prompt_version": PROMPT_VERSION, "bbox_format": "xywh_normalized", "style_catalog": catalog,
                   "images": [{"attachment_index": index + 1, **row} for index, row in enumerate(batch)]}
        images = [{"path": str(Path(by_id[row["image_id"]]["local_path"]).resolve()), "sha256": row["image_sha256"],
                   "candidate_id": row["image_id"], "role": "original_image"} for row in batch]
        schema = response_schema([row["image_id"] for row in batch], [item["style_id"] for item in catalog])
        key = hashlib.sha256(encoded({"system": system, "payload": payload, "images": images, "schema": schema,
                                     "model": configuration["model"], "effort": configuration["reasoning_effort"],
                                     **({"execution_config": configuration} if execution_config is not None else {})})).hexdigest()
        batches.append({"batch_id": f"batch-{len(batches) + 1:04d}", "input_key": key, "payload": payload,
                        "images": images, "schema": schema})
    plan = {"schema_version": "prism.design_cards_plan.v1", "sample_ref": reference(sample_path),
            "prior_observations_ref": reference(prior_path), "script_ref": reference(__file__),
            "runtime_ref": configuration["runtime_ref"], "policy_ref": reference(POLICY),
            "style_reference_refs": catalog_refs, "prompt_version": PROMPT_VERSION,
            "model": configuration["model"], "reasoning_effort": configuration["reasoning_effort"],
            "batch_size": batch_size, "workers": workers, "image_count": len(rows), "planned_model_calls": len(batches),
            "automatic_retries": False, "invalid_inputs": invalid, "context_warnings": context_warnings,
            "execution_scope_note": "规则更新或缓存拒绝不授权重提；先列事实缺口，再仅对明确选定的有界清单使用 --execute。历史冻结 DNA 可供 B 读取，不等于已补齐当前观察要求。",
            "cross_run_reuse": reuse,
            "batches": [{"batch_id": item["batch_id"], "input_key": item["input_key"],
                         "image_ids": [row["candidate_id"] for row in item["images"]]} for item in batches]}
    if execution_config is not None:
        plan["execution_config"] = configuration
    return plan, batches, {"sample": sample, "system": system, "catalog": catalog,
                           "reused_cards": reused_cards, "reused_ledger": reused_ledger}


def checked_answer(folder: Path, batch: dict, system: str, *, execution_config: dict | None = None) -> tuple[dict, dict]:
    """缓存不是文件名命中：实际输入、Schema、原回答、回执和附件全部核对。"""
    configuration = _execution_config(execution_config)
    receipt = json.loads((folder / "receipt.json").read_bytes())
    if receipt.get("status") != "completed":
        raise ValueError("既有调用失败；不自动重试")
    if execution_config is None and receipt.get("transport") == "project_langchain_sdk":
        raise ValueError("工程 SDK 与历史默认 CLI 传输不同，不能隐式复用")
    if (folder / "system.txt").read_text().rstrip("\n") != system.rstrip("\n"):
        raise ValueError("既有 system 与本次不匹配")
    if json.loads((folder / "payload.json").read_bytes()) != batch["payload"]:
        raise ValueError("既有 payload 与本次不匹配")
    if read_ref(receipt["schema_ref"]) != batch["schema"] or receipt.get("images") != batch["images"]:
        raise ValueError("既有 Schema 或附件与本次不匹配")
    if (receipt.get("requested_model") != configuration["model"]
            or receipt.get("requested_reasoning_effort") != configuration["reasoning_effort"]):
        raise ValueError("既有请求模型配置与本次不匹配")
    if configuration["actual_model_policy"] == "exact" and receipt.get("actual_model") not in (None, configuration["model"]):
        raise ValueError("实际模型已知且与请求模型不同，不能兼容复用")
    if execution_config is not None and any(receipt.get(key) != configuration[key]
                                            for key in ("runtime_ref", "transport", "actual_model_policy", "model_options", "configuration_refs")):
        raise ValueError("实际工程运行器或传输身份与冻结计划不匹配")
    if execution_config is not None:
        sdk_request = read_ref(receipt["sdk_request_ref"])
        if sdk_request.get("model_id") != configuration["model"] or sdk_request.get("model_options") != receipt.get("model_options"):
            raise ValueError("工程实际请求的模型或参数不匹配")
        messages = sdk_request["messages"]
        if len(messages) != 2 or messages[0] != {"role": "system", "content": system} or messages[1].get("role") != "user":
            raise ValueError("工程实际请求的消息与阶段 system 不匹配")
        content = messages[1]["content"]
        if (len(content) != len(batch["images"]) + 1 or content[0].get("type") != "text"
                or any(block.get("type") != "image" for block in content[1:])):
            raise ValueError("工程实际请求含有未登记文本或附件类型")
        sent_images = content[1:]
        if len(sent_images) != len(batch["images"]) or any(
                hashlib.sha256(base64.b64decode(block["base64"], validate=True)).hexdigest() != image["sha256"]
                for block, image in zip(sent_images, batch["images"])):
            raise ValueError("工程实际请求没有完整附上冻结原图字节")
    datetime.fromisoformat(receipt["started_at"])
    request_path = folder / "request.json"
    if request_path.exists():
        request = json.loads(request_path.read_bytes())
        fields = ("requested_model", "requested_reasoning_effort", "started_at", "images", "prompt_ref", "schema_ref")
        if any(request.get(key) != receipt.get(key) for key in fields):
            raise ValueError("原请求记录与完成回执的模型/输入/Schema/时间绑定不一致")
        for key in ("runtime_ref", "event_parser_ref", "argv", "transport", "actual_model_policy", "model_options", "sdk_request_ref"):
            if key in request and request[key] != receipt.get(key):
                raise ValueError(f"原请求与回执的历史执行元数据不一致：{key}")
    prompt_ref = receipt["prompt_ref"]
    if digest(prompt_ref["path"]) != prompt_ref["sha256"]:
        raise ValueError("实际 Prompt SHA 不一致")
    prompt = Path(prompt_ref["path"]).read_text()
    marker = "=== ACTUAL PAYLOAD ==="
    if marker not in prompt or json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0] != batch["payload"]:
        raise ValueError("实际发送 Prompt 的 payload 与计划不符")
    if execution_config is not None and content[0]["text"].rstrip("\n") != prompt.split(marker, 1)[1].lstrip("\n").rstrip("\n"):
        raise ValueError("工程实际发送的用户文本与冻结 Prompt 不符")
    # 旧运行的调度脚本 SHA 可以不同，但实际发送的阶段规则必须逐字相同。
    stage_marker, attachment_marker = "=== STAGE SYSTEM (verbatim) ===\n", "=== ORDERED ATTACHMENT IDENTITY ==="
    sent_system = (prompt.split(stage_marker, 1)[1].split(attachment_marker, 1)[0]
                   if stage_marker in prompt else prompt.split(marker, 1)[0])
    if sent_system.rstrip("\n") != system.rstrip("\n"):
        raise ValueError("实际发送 Prompt 的 system 与当前规则不符")
    answer = read_ref(receipt["answer_ref"])
    if Path(receipt["answer_ref"]["path"]).resolve() != (folder / "answer.json").resolve():
        raise ValueError("回答引用跨调用目录")
    for image in batch["images"]:
        if digest(image["path"]) != image["sha256"]:
            raise ValueError("附件已改变")
    return answer, receipt


def compile_answer(answer: dict, receipt: dict, folder: Path, rows: list[dict], style_ids: list[str]) -> tuple[list[dict], list[dict]]:
    """保留卡级失败位置与原答，不为了形式过关修写模型值。"""
    cards, ledger = [], []
    expected = {row["image_id"]: row for row in rows}
    returned = answer.get("images", [])
    counts = Counter(row.get("image_id") for row in returned if isinstance(row, dict))
    if any(image_id not in expected for image_id in counts):
        raise ValueError("原答含请求外图像")
    for image_id, row in expected.items():
        errors, valid, branches = [], [], Counter()
        if counts[image_id] != 1:
            errors.append("原答缺失或重复本图")
        else:
            index = next(i for i, item in enumerate(returned) if item["image_id"] == image_id)
            for card_index, raw in enumerate(returned[index].get("cards", [])):
                pointer = f"/images/{index}/cards/{card_index}"
                try:
                    validate_card(raw, style_ids)
                    branch = raw["branch"]
                    if branches[branch] >= {"ID": 1, "CMF": 2}[branch]:
                        raise ValueError("超过本图分支卡数上限")
                    branches[branch] += 1
                    card = {**deepcopy(raw), "card_id": f"{image_id}:{branch}:{card_index + 1}",
                            "image_id": image_id, "image_sha256": row["sha256"],
                            "local_path": str(Path(row["local_path"]).resolve()), "bbox_format": "xywh_normalized",
                            "sources": deepcopy(row.get("sources", [])), "source_kind": row.get("source_kind", "unknown"),
                            "provenance": {"answer_ref": receipt["answer_ref"], "pointer": pointer,
                                           "receipt_ref": reference(folder / "receipt.json"), "prompt_ref": receipt["prompt_ref"],
                                           "prompt_version": PROMPT_VERSION, "requested_model": receipt["requested_model"],
                                           "actual_model": receipt.get("actual_model"),
                                           "reasoning_effort": receipt.get("requested_reasoning_effort"),
                                           "assessed_at": receipt["started_at"]}}
                    valid.append(card)
                except (ValueError, KeyError, TypeError, jsonschema.ValidationError) as exc:
                    errors.append({"pointer": pointer, "error": str(exc)})
            if not valid and not errors:
                errors.append("模型未选择可用对象；空卡是终态排除，不表示图片无设计价值")
        cards.extend(valid)
        ledger.append({"image_id": image_id, "sha256": row["sha256"], "status": "observed" if valid else "failed",
                       "card_ids": [card["card_id"] for card in valid], "errors": errors,
                       "answer_ref": receipt["answer_ref"], "receipt_ref": reference(folder / "receipt.json")})
    return cards, ledger


def fatal_call_failure(folder: Path, error: str) -> bool:
    """仅鉴权、配额和限流停发全局队列；普通响应/卡片校验错误仅影响本批。"""
    details = [error]
    for name in ("receipt.json", "stderr.txt"):
        path = folder / name
        if path.exists():
            details.append(path.read_text(errors="replace")[-32768:])
    pattern = (r"unauthorized|authentication(?:[_ -]error|[_ -]required| failed)?|invalid[_ -]api[_ -]key|"
               r"insufficient[_ -]quota|rate[_ -]limit|usage[_ -]limit|quota.{0,20}(?:exceed|exhaust)|"
               r"too many requests|\bHTTP\s*(?:401|403|429)\b|鉴权|认证失败|配额|限流|额度(?:不足|耗尽)")
    return bool(re.search(pattern, "\n".join(details), re.I))


def prepared_header(manifest_path: str | Path) -> tuple[dict, dict, dict]:
    """检查冻结容器与全体台账结构；逐图原答核验另行执行，便于有界复用。"""
    manifest = json.loads(Path(manifest_path).read_bytes())
    if manifest.get("schema_version") != PREPARED_VERSION:
        raise ValueError("不是关系型设计卡冻结清单")
    document = read_ref(manifest["design_cards_ref"])
    if document.get("schema_version") != VERSION:
        raise ValueError("关系型卡版本不匹配")
    sample = read_ref(document["sample_ref"])
    read_ref(document["prior_observations_ref"])
    if manifest["sample_ref"] != document["sample_ref"] or manifest["prior_observations_ref"] != document["prior_observations_ref"]:
        raise ValueError("冻结清单和卡文档输入引用不一致")
    expected = {row["image_id"]: row for row in sample["images"]}
    ledger = document["images"]
    if len(ledger) != len(expected) or {row["image_id"] for row in ledger} != set(expected):
        raise ValueError("存在未入账图片")
    if any(row["status"] not in {"observed", "failed"} or row["sha256"] != expected[row["image_id"]]["sha256"] for row in ledger):
        raise ValueError("图片未终态或身份不一致")
    cards = document["cards"]
    if len({card["card_id"] for card in cards}) != len(cards):
        raise ValueError("卡 ID 重复")
    by_image = {image_id: set() for image_id in expected}
    for card in cards:
        if card["image_id"] not in expected:
            raise ValueError("卡属于样本外图片")
        by_image[card["image_id"]].add(card["card_id"])
    for row in ledger:
        ids = row.get("card_ids", [])
        if (len(ids) != len(set(ids)) or set(ids) != by_image[row["image_id"]]
                or (row["status"] == "observed") != bool(ids)):
            raise ValueError("逐图台账与有效卡索引不同")
    return manifest, document, expected


def validate_frozen_cards(cards: list[dict], expected: dict, document: dict) -> None:
    """只校验传入卡的原图、来源、原答与冻结视窗；不改写或补齐模型事实。"""
    styles = [item["style_id"] for item in document["style_catalog"]]
    answers, receipts = {}, {}
    for card in cards:
        row = expected[card["image_id"]]
        if (card["image_sha256"] != row["sha256"] or digest(card["local_path"]) != row["sha256"]
                or Path(card["local_path"]).resolve() != Path(row["local_path"]).resolve() or card["sources"] != row.get("sources", [])):
            raise ValueError("卡借用其他图片或来源")
        proof = card["provenance"]
        key = (proof["answer_ref"]["path"], proof["answer_ref"]["sha256"])
        if key not in answers:
            answers[key] = read_ref(proof["answer_ref"])
        receipt_key = (proof["receipt_ref"]["path"], proof["receipt_ref"]["sha256"])
        if receipt_key not in receipts:
            receipts[receipt_key] = read_ref(proof["receipt_ref"])
        receipt = receipts[receipt_key]
        if receipt.get("status") != "completed" or receipt["answer_ref"] != proof["answer_ref"]:
            raise ValueError("卡没有已完成原答回执")
        if proof["requested_model"] != receipt.get("requested_model") or proof["assessed_at"] != receipt.get("started_at"):
            raise ValueError("卡模型或时间未绑定实际回执")
        if (proof.get("actual_model") != receipt.get("actual_model")
                or proof.get("reasoning_effort") != receipt.get("requested_reasoning_effort")):
            raise ValueError("卡实际模型或推理配置未绑定完成回执")
        parts = proof["pointer"].split("/")
        if len(parts) != 5 or parts[1] != "images" or parts[3] != "cards":
            raise ValueError("卡原答 pointer 格式错误")
        owner = answers[key]["images"][int(parts[2])]
        raw = owner["cards"][int(parts[4])]
        if owner["image_id"] != card["image_id"] or any(card.get(key) != value for key, value in raw.items()):
            raise ValueError("卡内容与原答不一致")
        validate_card(raw, styles)
        if (card["image_id"], card["image_sha256"]) not in {(image.get("candidate_id"), image.get("sha256")) for image in receipt.get("images", [])}:
            raise ValueError("卡所属原图未实际附给模型")
        prompt_ref = proof["prompt_ref"]
        if prompt_ref != receipt["prompt_ref"] or digest(prompt_ref["path"]) != prompt_ref["sha256"]:
            raise ValueError("卡 Prompt 引用损坏")
        prompt = Path(prompt_ref["path"]).read_text()
        payload = json.JSONDecoder().raw_decode(prompt.split("=== ACTUAL PAYLOAD ===", 1)[1].lstrip())[0]
        if payload.get("prompt_version") != proof["prompt_version"]:
            raise ValueError("卡 Prompt 版本与实际发送不符")


def load_prepared(manifest_path: str | Path) -> dict:
    """Stage B 只读核验历史证据；保留原 Prompt 身份，不补字段或授予当前观察覆盖。"""
    _, document, expected = prepared_header(manifest_path)
    validate_frozen_cards(document["cards"], expected, document)
    return document


def find_reusable_images(paths: list[Path], inputs: list[dict], rows: dict,
                         system: str, catalog: list[dict], *, execution_config: dict | None = None) -> tuple[dict, list[dict], list[dict]]:
    """只检索显式授权的冻结清单；按图比较真实请求，不用生成器文件 SHA 判语义兼容。

    样本增减、排序、批大小不影响逐图命中；暂不迁移图片别名、来源、路径或取景。
    只读取候选图的原图及原答，不遍历项目目录，也不执行历史模型回放。
    """
    sources, loaded, rejected = [], [], []
    seen_paths = set()
    for path in paths:
        path = Path(path).resolve()
        if path in seen_paths:
            continue
        seen_paths.add(path)
        source_ref = {"path": str(path), "sha256": None}
        try:
            source_ref = reference(path)
            manifest, document, expected = prepared_header(path)
            source_plan = read_ref(document["plan_ref"])
            if source_plan.get("prompt_version") != PROMPT_VERSION or document["style_catalog"] != catalog:
                raise ValueError("冻结 Prompt 版本或风格目录与本次提取请求不兼容；这不是历史 DNA 作废或重提授权")
            source_cards = {}
            for card in document["cards"]:
                source_cards.setdefault(card["image_id"], []).append(card)
            loaded.append({"ref": source_ref, "design_cards_ref": manifest["design_cards_ref"],
                           "document": document, "expected": expected,
                           "cards": source_cards, "ledger": {row["image_id"]: row for row in document["images"]}})
        except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            rejected.append({"image_id": None, "source_ref": source_ref,
                             "reason": f"source_invalid: {type(exc).__name__}: {exc}"[:1500]})
        sources.append(source_ref)
    reused_cards, reused_ledger, matches = [], [], []
    style_ids = [item["style_id"] for item in catalog]
    for current_input in inputs:
        image_id = current_input["image_id"]
        row = rows[image_id]
        for source in loaded:
            try:
                previous = source["expected"].get(image_id)
                if previous is None:
                    raise ValueError("image_id 未在该冻结样本中；不按 SHA 自动改写图片别名")
                if (previous["sha256"] != row["sha256"]
                        or Path(previous["local_path"]).resolve() != Path(row["local_path"]).resolve()
                        or previous.get("sources", []) != row.get("sources", [])
                        or previous.get("source_kind", "unknown") != row.get("source_kind", "unknown")):
                    raise ValueError("原图 SHA、路径或来源元数据不一致")
                old_ledger, old_cards = source["ledger"][image_id], source["cards"].get(image_id, [])
                if old_ledger["status"] != "observed" or not old_cards:
                    raise ValueError("历史图无有效卡；失败或空卡不冒充成功复用")
                validate_frozen_cards(old_cards, source["expected"], source["document"])
                receipt_refs = {json.dumps(card["provenance"]["receipt_ref"], sort_keys=True) for card in old_cards}
                if len(receipt_refs) != 1:
                    raise ValueError("单图卡跨多个原答，不能确认一致的对象/取景契约")
                proof = old_cards[0]["provenance"]
                if old_ledger.get("receipt_ref") != proof["receipt_ref"] or old_ledger.get("answer_ref") != proof["answer_ref"]:
                    raise ValueError("旧图台账没有绑定卡的实际调用")
                folder = Path(proof["receipt_ref"]["path"]).parent
                payload = json.loads((folder / "payload.json").read_bytes())
                if (set(payload) != {"prompt_version", "bbox_format", "style_catalog", "images"}
                        or payload["prompt_version"] != PROMPT_VERSION or payload["bbox_format"] != "xywh_normalized"
                        or payload["style_catalog"] != catalog):
                    raise ValueError("实际请求的 Prompt、坐标或风格协议不匹配")
                owners = [item for item in payload["images"] if item.get("image_id") == image_id]
                if len(owners) != 1 or {key: value for key, value in owners[0].items() if key != "attachment_index"} != current_input:
                    raise ValueError("实际发送的逐图旧观察/R5 上下文与当前请求不匹配")
                old_ids = [item["image_id"] for item in payload["images"]]
                if len(set(old_ids)) != len(old_ids):
                    raise ValueError("旧请求含重复图片身份")
                receipt = read_ref(proof["receipt_ref"])
                attachments = {image["candidate_id"]: image for image in receipt["images"]}
                if set(attachments) != set(old_ids) or len(receipt["images"]) != len(old_ids):
                    raise ValueError("旧请求图片身份与附件集合不同")
                batch = {"payload": payload, "images": receipt["images"],
                         "schema": response_schema(old_ids, style_ids)}
                answer, receipt = checked_answer(folder, batch, system, execution_config=execution_config)
                # 重新编译原答只作机械验证，不产生新事实；保留同图局部失败和原始 pointer。
                # 二次复用的快照可能只保留原批次的一张图；其他图只作原答结构核验，不复制其卡。
                original_rows = [source["expected"].get(old_id, {
                    "image_id": old_id, "sha256": attachments[old_id]["sha256"],
                    "local_path": attachments[old_id]["path"]}) for old_id in old_ids]
                compiled, original_ledger = compile_answer(answer, receipt, folder,
                                                           original_rows, style_ids)
                actual_cards = [card for card in compiled if card["image_id"] == image_id]
                actual_ledger = next(item for item in original_ledger if item["image_id"] == image_id)
                if (sorted(actual_cards, key=lambda card: card["card_id"]) != sorted(old_cards, key=lambda card: card["card_id"])
                        or any(old_ledger.get(key) != value for key, value in actual_ledger.items())):
                    raise ValueError("冻结对象/取景或台账不等于当前协议对原答的合法编译结果")
                reuse_proof = {"prepared_ref": source["ref"], "design_cards_ref": source["design_cards_ref"]}
                reused_cards.extend(deepcopy(old_cards))
                reused_ledger.append({**deepcopy(old_ledger), "cross_run_reuse": reuse_proof})
                matches.append({"image_id": image_id, "card_ids": [card["card_id"] for card in old_cards], **reuse_proof})
                break
            except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError,
                    StopIteration, jsonschema.ValidationError) as exc:
                rejected.append({"image_id": image_id, "source_ref": source["ref"],
                                 "reason": f"incompatible: {type(exc).__name__}: {exc}"[:1500]})
    report = {"source_refs": sources, "matched_images": len(matches), "matched_cards": len(reused_cards),
              "matches": matches, "rejections": rejected,
              "not_reused_image_ids": [row["image_id"] for row in inputs
                                       if row["image_id"] not in {item["image_id"] for item in matches}],
              "scope": "仅显式快照、同 image_id/SHA/路径/来源和兼容实际请求；不扫描全库或迁移别名"}
    return report, reused_cards, reused_ledger


def coverage_counts(total: int, ledger: list[dict], cards: list[dict]) -> dict:
    """成功率仅为至少一张合法卡的图像覆盖率，不代表视觉准确率；严格大于 90%。"""
    observed = sum(row["status"] == "observed" for row in ledger)
    failed = sum(row["status"] == "failed" for row in ledger)
    coverage = {branch: len({card["image_id"] for card in cards if card["branch"] == branch}) for branch in ("ID", "CMF")}
    return {"images": total, "observed": observed, "failed": failed, "pending": total - observed - failed,
            "success_rate": observed / total, "success_definition": "image_with_at_least_one_valid_card",
            "strictly_over_90_percent": observed * 10 > total * 9, "visual_accuracy_claimed": False,
            "cards": len(cards), "cards_by_branch": dict(Counter(card["branch"] for card in cards)),
            "images_by_branch": coverage, "image_coverage_by_branch": {key: value / total for key, value in coverage.items()}}


def run(sample_path: Path, prior_path: Path, out: Path, *, batch_size: int = 1, workers: int = 10,
        execute: bool = False, resume: bool = False, resume_after_quota_reset: bool = False,
        reuse_prepared: list[Path] | None = None, executor=None, execution_config: dict | None = None) -> dict:
    """每图至多一次提取；配额暂停后显式确认额度恢复才继续尚未发送的图。"""
    if resume_after_quota_reset and not (execute and resume):
        raise ValueError("--resume-after-quota-reset 必须同时使用 --execute --resume")
    if execution_config is not None and executor is None:
        raise ValueError("工程执行配置必须提供对应执行器，禁止误回退到默认 CLI")
    plan, batches, context = make_plan(sample_path, prior_path, batch_size, workers, reuse_prepared,
                                       execution_config=execution_config)
    if not execute:
        return {**plan, "dry_run": True, "out": str(out.resolve())}
    out = out.resolve()
    if out.exists():
        if not resume or json.loads((out / "plan.json").read_bytes()) != plan:
            raise ValueError("输出目录已存在或 resume 输入/Prompt/模型配置不完全匹配")
    else:
        if resume:
            raise ValueError("resume 只用于已存在且已写计划的运行")
        out.mkdir(parents=True)
        write_new(out / "plan.json", plan)
    with execution_lock(out):
        if (out / "prepared-manifest.json").exists():
            return {"resumed_frozen": True, "counts": load_prepared(out / "prepared-manifest.json")["counts"]}
        progress_path = out / "progress.json"
        if progress_path.exists():
            previous = json.loads(progress_path.read_bytes())
            if previous.get("status") == "paused_quota_or_auth" and not resume_after_quota_reset:
                return {**previous, "resume_requires": "确认额度/鉴权恢复后使用 --resume --execute --resume-after-quota-reset"}
        return execute_plan(plan, batches, context, out, workers=workers,
                            quota_reset_confirmed=resume_after_quota_reset, executor=executor)


def execute_plan(plan: dict, batches: list[dict], context: dict, out: Path, *, workers: int,
                 quota_reset_confirmed: bool, executor=None) -> dict:
    """每批独立持久化；恢复只读取已发批次，未知中断视为失败以避免重复提取。"""
    if executor is None and batches:
        sys.path.insert(0, str(CLUSTER / "scripts"))
        executor = importlib.import_module("model_runtime").execute_structured
    start, started_at = monotonic(), now()
    rows = {row["image_id"]: row for row in context["sample"]["images"]}
    cards = deepcopy(context["reused_cards"])
    ledger, calls = deepcopy(context["reused_ledger"]) + list(plan["invalid_inputs"]), []
    catalog_ids = [item["style_id"] for item in context["catalog"]]
    execution_id = f"execution-{len(list((out / 'executions').glob('*.started.json'))) + 1:04d}"
    write_new(out / "executions" / f"{execution_id}.started.json", {
        "started_at": started_at, "quota_reset_confirmed": quota_reset_confirmed, "plan_ref": reference(out / "plan.json")})

    def process(batch):
        folder = out / "model-calls" / batch["batch_id"]
        attempt_path = out / "attempts" / f"{batch['batch_id']}.json"
        result_path = out / "batch-results" / f"{batch['batch_id']}.json"
        saved = json.loads(result_path.read_bytes()) if result_path.exists() else None
        if saved is not None and saved["input_key"] != batch["input_key"]:
            raise ValueError("批次持久化结果的输入 key 不匹配")
        cached = folder.exists() or attempt_path.exists() or saved is not None
        report = {"batch_id": batch["batch_id"], "input_key": batch["input_key"], "reused_existing_call": cached,
                  "model_invoked_this_execution": False, "call_attempted_this_execution": False}
        if saved is not None and saved["report"]["status"] == "failed":
            return saved["cards"], saved["images"], {
                **saved["report"], **report, "stop_new_calls": False,
                "previous_fatal_failure": bool(saved["report"].get("stop_new_calls"))
                or fatal_call_failure(folder, saved["report"].get("error", ""))}
        try:
            if not cached:
                # 在调用前登记一次性尝试；若进程在创建模型目录前中断，也不猜测并重发。
                write_new(attempt_path, {"input_key": batch["input_key"], "started_at": now(), "execution_id": execution_id})
                report["call_attempted_this_execution"] = True
                executor(folder, system=context["system"], payload=batch["payload"], images=batch["images"], schema=batch["schema"])
            answer, receipt = checked_answer(folder, batch, context["system"], execution_config=plan.get("execution_config"))
            batch_cards, batch_ledger = compile_answer(answer, receipt, folder,
                [rows[image["candidate_id"]] for image in batch["images"]], catalog_ids)
            report.update(status="completed", model_invoked_this_execution=not cached, seconds=receipt.get("seconds"),
                          receipt_ref=reference(folder / "receipt.json"), stop_new_calls=False)
            if saved is not None and (saved["cards"] != batch_cards or saved["images"] != batch_ledger):
                raise ValueError("已保存卡与实际原回答不一致")
            return batch_cards, batch_ledger, report
        except Exception as exc:
            report.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                          stop_new_calls=not cached and fatal_call_failure(folder, str(exc)),
                          previous_fatal_failure=cached and fatal_call_failure(folder, str(exc)))
            if (folder / "receipt.json").exists():
                report["receipt_ref"] = reference(folder / "receipt.json")
                try:
                    receipt = json.loads((folder / "receipt.json").read_bytes())
                except json.JSONDecodeError:
                    receipt = {}  # 中断/损坏的回执不能当作成功，也不能触发再次请求。
                report["model_invoked_this_execution"] = not cached and bool(
                    receipt.get("started_turn_count") or receipt.get("usage", {}).get("llm_request_count"))
            failures = [{"image_id": image["candidate_id"], "sha256": image["sha256"], "status": "failed", "card_ids": [],
                         "errors": [report["error"]]} for image in batch["images"]]
            return [], failures, report

    def record(batch_cards, batch_ledger, report):
        path = out / "batch-results" / f"{report['batch_id']}.json"
        if not path.exists():
            write_new(path, {"input_key": report["input_key"], "cards": batch_cards, "images": batch_ledger, "report": report})
        cards.extend(batch_cards)
        ledger.extend(batch_ledger)
        calls.append(report)

    def progress(status: str, in_flight_ids: list[str] | None = None) -> dict:
        current = coverage_counts(len(rows), ledger, cards)
        flight = set(in_flight_ids or [])
        completed = {row["image_id"] for row in ledger}
        unattempted = set(rows) - completed - flight
        snapshot = {"schema_version": "prism.design_cards_progress.v1", "status": status, "updated_at": now(),
                    "execution_id": execution_id, "counts": current, "all_images_terminal": current["pending"] == 0,
                    "in_flight_image_ids": sorted(flight), "not_attempted_image_ids": sorted(unattempted),
                    "not_attempted_count": len(unattempted), "plan_ref": reference(out / "plan.json"),
                    "images": sorted(ledger + [{"image_id": image_id, "sha256": rows[image_id]["sha256"],
                                                "status": "not_attempted", "errors": []} for image_id in unattempted],
                                     key=lambda item: item["image_id"])}
        atomic_json(out / "progress.json", snapshot, replace=True)
        return snapshot

    # 先恢复所有已发批次，再调度新批次；恢复过程没有模型调用，也不重做失败图。
    fresh_batches = []
    for batch in batches:
        if any(path.exists() for path in (out / "batch-results" / f"{batch['batch_id']}.json",
                                         out / "attempts" / f"{batch['batch_id']}.json",
                                         out / "model-calls" / batch["batch_id"])):
            record(*process(batch))
        else:
            fresh_batches.append(batch)
    progress("running")
    # 主进程可能在错误回执落盘后、暂停进度写盘前中断；恢复也必须承认该额度故障。
    stopped = not quota_reset_confirmed and any(call.get("previous_fatal_failure") for call in calls)
    next_batch = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        in_flight = {}
        while in_flight or (next_batch < len(fresh_batches) and not stopped):
            # 有界滚动调度；发生全局故障后只等待已发请求，不再把整个全集排入执行器。
            while not stopped and len(in_flight) < workers and next_batch < len(fresh_batches):
                batch = fresh_batches[next_batch]
                in_flight[pool.submit(process, batch)] = batch
                next_batch += 1
            progress("running", [image["candidate_id"] for batch in in_flight.values() for image in batch["images"]])
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                in_flight.pop(future)
                batch_cards, batch_ledger, report = future.result()
                record(batch_cards, batch_ledger, report)
                stopped = stopped or report["stop_new_calls"]
                current = progress("running", [image["candidate_id"] for batch in in_flight.values() for image in batch["images"]])
                print(json.dumps({"stage": "design_cards", "terminal_images": len(ledger), "total_images": len(rows),
                                  "observed_images": current["counts"]["observed"], "failed_images": current["counts"]["failed"],
                                  "valid_cards": len(cards), "batch": report["batch_id"], "status": report["status"]}, ensure_ascii=False), flush=True)
    counts = coverage_counts(len(rows), ledger, cards)
    execution = {"started_at": started_at, "finished_at": now(), "wall_seconds": round(monotonic() - start, 3),
                 "model_calls_this_execution": sum(item["model_invoked_this_execution"] for item in calls),
                 "call_attempts_this_execution": sum(item["call_attempted_this_execution"] for item in calls),
                 "stopped_new_calls_after_fatal_failure": stopped,
                 "cached_calls": sum(item["reused_existing_call"] for item in calls), "automatic_retries": False,
                 "cross_run_reused_images": len(context["reused_ledger"]),
                 "cross_run_reused_cards": len(context["reused_cards"]),
                 "quota_reset_confirmed": quota_reset_confirmed, "execution_id": execution_id,
                 "calls": sorted(calls, key=lambda item: item["batch_id"])}
    write_new(out / "executions" / f"{execution_id}.finished.json", execution)
    if counts["pending"]:
        snapshot = progress("paused_quota_or_auth" if stopped else "incomplete")
        snapshot["execution"] = execution
        atomic_json(out / "progress.json", snapshot, replace=True)
        return snapshot  # 未发送不是永久失败，更不能发布全部终态的冻结清单。
    document = {"schema_version": VERSION, "created_at": now(), "bbox_format": "xywh_normalized",
                "sample_ref": plan["sample_ref"], "prior_observations_ref": plan["prior_observations_ref"],
                "plan_ref": reference(out / "plan.json"), "images": sorted(ledger, key=lambda row: row["image_id"]),
                "cards": sorted(cards, key=lambda card: card["card_id"]), "style_catalog": context["catalog"],
                "counts": counts, "execution": execution, "human_approved": False, "visual_board_approved": False,
                "cross_run_reuse": plan["cross_run_reuse"],
                "legacy_r5_modified": False, "coverage_limit": "每图最多 1 ID、2 CMF；并非穷尽对象或完整规范 DNA"}
    if (out / "design-cards.json").exists():
        # 允许从最终设计卡已发布、manifest 尚未发布的极短中断窗口恢复。
        existing = json.loads((out / "design-cards.json").read_bytes())
        if any(existing[key] != document[key] for key in ("sample_ref", "prior_observations_ref", "plan_ref", "images", "cards", "counts")):
            raise ValueError("已有最终设计卡不匹配本次恢复结果")
        document = existing
        execution = existing["execution"]
    else:
        write_new(out / "design-cards.json", document)
    manifest = {"schema_version": PREPARED_VERSION, "created_at": now(), "design_cards_ref": reference(out / "design-cards.json"),
                "sample_ref": plan["sample_ref"], "prior_observations_ref": plan["prior_observations_ref"],
                "counts": counts, "execution": execution, "all_images_terminal": True, "visual_approval_granted": False,
                "cross_run_reuse": plan["cross_run_reuse"],
                "success_rate_gate": {"required": ">0.90", "passed": counts["strictly_over_90_percent"],
                                      "basis": "至少一个合法设计卡的图像数/全部冻结样本数，不是视觉准确率"}}
    write_new(out / "prepared-manifest.json", manifest)
    load_prepared(out / "prepared-manifest.json")
    progress("completed")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--prior-observations", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-after-quota-reset", action="store_true",
                        help="仅在已确认额度/鉴权恢复后续未发送图；绝不重做已发失败图")
    parser.add_argument("--reuse-prepared", type=Path, action="append", default=[],
                        help="显式可复用的冻结清单，可重复；逐图核验真实请求/原答，只给未命中图排调用")
    args = parser.parse_args()
    result = run(args.sample.resolve(), args.prior_observations.resolve(), args.out, batch_size=args.batch_size,
                 workers=args.workers, execute=args.execute, resume=args.resume,
                 resume_after_quota_reset=args.resume_after_quota_reset, reuse_prepared=args.reuse_prepared)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

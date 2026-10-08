"""用研文本聚类的离线清单、覆盖检查与结果编译；不访问图片或调用模型。"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
DIMENSIONS = {
    "style", "color", "material", "finish", "form", "pattern", "detail",
    "proportion", "interaction", "sensory", "emotion", "identity", "lifestyle",
    "context", "purchase", "function", "other_design",
}
CONTEXT_DIMENSIONS = {"identity", "lifestyle", "context", "purchase", "function"}
STANCES = {"prefer", "avoid", "conditional", "neutral"}
RETENTIONS = {"no_answer", "image_reference_only", "context_only", "non_design", "unclear"}
USER_FIELDS = {"id", "bid", "name", "profile", "aesthetic_research", "demand_research", "image_preferences", "ppt_images", "ppt_supplement"}
ORIGIN_FIELDS = {"source_type", "source_file", "source_slide", "source_language", "translated_to"}
COMMON_FIELDS = {"id", "bid", "ref_pic", "ref_pic_links"} | ORIGIN_FIELDS
QA_FIELDS = COMMON_FIELDS | {"answer_type", "scenario_type", "question_type", "question", "ai_analysis"}
DEMAND_FIELDS = COMMON_FIELDS | {"ai_index", "scenario"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fields(value: Any, expected: set[str], location: str) -> None:
    require(isinstance(value, dict), f"{location} 必须是对象")
    require(set(value) == expected, f"{location} 字段错误；缺少 {sorted(expected - set(value))}，多余 {sorted(set(value) - expected)}")


def string(value: Any, location: str, *, empty: bool = False) -> str:
    require(isinstance(value, str) and (empty or bool(value.strip())), f"{location} 必须是{'可空' if empty else '非空'}字符串")
    return value


def items(value: Any, location: str) -> list:
    require(isinstance(value, list), f"{location} 必须是数组")
    return value


def ids(value: Any, valid: set[str], location: str, *, empty: bool = True) -> list[str]:
    rows = items(value, location)
    require(all(isinstance(row, str) for row in rows), f"{location} ID 必须是字符串")
    require(len(rows) == len(set(rows)), f"{location} 含重复 ID")
    require(empty or bool(rows), f"{location} 至少需要一个引用")
    require(set(rows) <= valid, f"{location} 含未知引用 {sorted(set(rows) - valid)}")
    return rows


def pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def profile_leaves(value: Any, pointer: str):
    """保留任意画像字段的全部叶值，空容器也登记，避免固定白名单遗漏新增画像。"""
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from profile_leaves(child, pointer + "/" + pointer_part(key))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from profile_leaves(child, pointer + f"/{index}")
    else:
        yield pointer, value


def inventory(path: Path) -> dict:
    """只读取指定 JSON；图片表、图片描述及文件内容不进入文本清单。"""
    root = read_json(path)
    users = root.get("users") if isinstance(root, dict) else root
    require(isinstance(users, list) and bool(users), "输入必须包含非空 users 数组")
    records, identities = [], []
    ignored: Counter = Counter()
    seen_users = set()

    def append(user_id: str, kind: str, field: str, value: Any, pointer: str, context: dict, row: dict) -> None:
        text = value if isinstance(value, str) else "" if value is None else dump(value)
        nature = {"profile": "profile_value", "question": "existing_analysis", "demand": "demand_text"}[kind]
        if kind == "question" and row.get("source_type") == "ppt_supplement":
            nature = "ppt_transcribed_text"
        records.append({
            "source_id": f"S{len(records) + 1:06d}", "user_id": user_id,
            "kind": kind, "field": field, "text": text, "value": value,
            "pointer": pointer, "original_id": row.get("id"), "original_bid": row.get("bid"),
            "context": context, "evidence_kind": nature,
            "origin": {key: row[key] for key in sorted(ORIGIN_FIELDS) if key in row},
        })

    for index, user in enumerate(users):
        require(isinstance(user, dict), f"users[{index}] 必须是对象")
        unknown = set(user) - USER_FIELDS
        require(not unknown, f"users[{index}] 存在尚未映射字段 {sorted(unknown)}，请明确文本归属后再准备")
        user_id = str(user.get("id") if user.get("id") is not None else "")
        require(bool(user_id) and user_id not in seen_users, f"用户 ID 缺失或重复：{user_id}")
        seen_users.add(user_id)
        prefix = f"/users/{index}" if isinstance(root, dict) else f"/{index}"
        profile = user.get("profile", {})
        require(isinstance(profile, dict), f"{user_id}.profile 必须是对象")
        identities.append({"id": user_id, "bid": user.get("bid"), "name": user.get("name"), "profile": profile})
        for pointer, value in profile_leaves(profile, prefix + "/profile"):
            append(user_id, "profile", pointer.split("/profile", 1)[1] or "/", value, pointer, {}, {})
        for section, field, kind, allowed, context_fields in (
            ("aesthetic_research", "ai_analysis", "question", QA_FIELDS, ("question", "scenario_type", "question_type", "answer_type")),
            ("demand_research", "ai_index", "demand", DEMAND_FIELDS, ("scenario",)),
        ):
            for row_index, row in enumerate(items(user.get(section, []), f"{user_id}.{section}")):
                require(isinstance(row, dict), f"{user_id}.{section}[{row_index}] 必须是对象")
                unknown = set(row) - allowed
                require(not unknown, f"{user_id}.{section}[{row_index}] 存在尚未映射字段 {sorted(unknown)}")
                append(user_id, kind, field, row.get(field), f"{prefix}/{section}/{row_index}/{field}", {key: row.get(key) for key in context_fields}, row)
                ignored["ref_pic_links"] += len(row.get("ref_pic_links") or [])
        for section in ("image_preferences", "ppt_images"):
            ignored[section] += len(user.get(section) or [])
        ignored["ppt_supplement_metadata"] += int(bool(user.get("ppt_supplement")))
    return {"schema_version": "user_research_text_sources.v1", "input_path": str(path.resolve()), "input_sha256": digest(path), "users": identities, "records": records, "excluded_sections": dict(ignored)}


def request(stage: str, prompt: str, payload: dict) -> dict:
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": dump(payload)}]
    return {"stage": stage, "messages": messages, "prompt_sha256": text_digest(dump(messages)), "message_characters": sum(len(item["content"]) for item in messages)}


def batches(sources: dict, prompt: str, max_chars: int) -> list[dict]:
    """默认保持整位用户；超限仅沿完整记录边界拆分，任何正文均不截短。"""
    result = []
    for user in sources["users"]:
        current = []

        def pack(rows: list) -> dict:
            payload = {"batch_id": f"B{len(result) + 1:04d}", "user": {"id": user["id"], "name": user["name"]}, "records": rows}
            built = request("extract", prompt, payload)
            built.update({"batch_id": payload["batch_id"], "source_ids": [row["source_id"] for row in rows]})
            return built

        for record in (row for row in sources["records"] if row["user_id"] == user["id"]):
            row = {key: record[key] for key in ("source_id", "kind", "field", "text", "context", "evidence_kind")}
            if current and pack(current + [row])["message_characters"] > max_chars:
                result.append(pack(current))
                current = []
            require(pack([row])["message_characters"] <= max_chars, f"{row['source_id']} 单条完整文本超出 {max_chars} 字符，请明确增大 --max-chars；不会截断")
            current.append(row)
        if current:
            result.append(pack(current))
    return result


def prepare(source: Path, out: Path | None, max_chars: int = 48000, dry_run: bool = False) -> dict:
    """把全部用户文本冻结到新目录；dry-run 仅计算清单和分包规模。"""
    sources = inventory(source)
    prompt = (SKILL_DIR / "references/extraction.md").read_text(encoding="utf-8")
    planned = batches(sources, prompt, max_chars)
    summary = {"users": len(sources["users"]), "records": len(sources["records"]), "records_by_kind": dict(Counter(row["kind"] for row in sources["records"])), "text_characters": sum(len(row["text"]) for row in sources["records"]), "batches": len(planned), "max_message_characters": max(item["message_characters"] for item in planned), "excluded_sections": sources["excluded_sections"], "model_calls": 0}
    if dry_run:
        return summary
    require(out is not None and not out.exists(), "--out 必须指定尚不存在的新运行目录")
    out.mkdir(parents=True)
    (out / "extractions").mkdir()
    write_json(out / "sources.json", sources)
    for name, relative in (("skill.md", "SKILL.md"), ("extraction.md", "references/extraction.md"), ("clustering.md", "references/clustering.md")):
        dest = out / "prompts" / name
        dest.parent.mkdir(exist_ok=True)
        dest.write_text((SKILL_DIR / relative).read_text(encoding="utf-8"), encoding="utf-8")
    for built in planned:
        write_json(out / "requests" / f"{built['batch_id']}.json", built)
    manifest = {"skill_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "input_sha256": sources["input_sha256"], "sources_sha256": digest(out / "sources.json"), "summary": summary, "max_chars": max_chars, "batches": [{"id": item["batch_id"], "source_ids": item["source_ids"], "request_sha256": digest(out / "requests" / f"{item['batch_id']}.json")} for item in planned], "prompt_files": {name: digest(out / "prompts" / name) for name in ("skill.md", "extraction.md", "clustering.md")}}
    write_json(out / "manifest.json", manifest)
    return {**summary, "run_dir": str(out.resolve())}


def load_run(run: Path) -> tuple[dict, dict]:
    manifest = read_json(run / "manifest.json")
    require(digest(run / "sources.json") == manifest["sources_sha256"], "冻结文本清单已改变，请新建运行")
    for name, expected in manifest["prompt_files"].items():
        require(digest(run / "prompts" / name) == expected, f"冻结 Prompt {name} 已改变")
    for batch in manifest["batches"]:
        require(digest(run / "requests" / f"{batch['id']}.json") == batch["request_sha256"], f"冻结请求 {batch['id']} 已改变")
    return manifest, read_json(run / "sources.json")


def execution(value: Any, prompt_sha256: str) -> dict:
    fields(value, {"model_id", "model_version", "executed_at", "prompt_sha256"}, "execution")
    for name in ("model_id", "model_version"):
        if value[name] is not None:
            string(value[name], name)
    string(value["executed_at"], "executed_at")
    timestamp = datetime.fromisoformat(value["executed_at"])
    require(timestamp.tzinfo is not None, "executed_at 必须有时区")
    require(value["prompt_sha256"] == prompt_sha256, "回复与本次完整请求的 prompt_sha256 不一致")
    return {**value, "traceability_gaps": [key for key in ("model_id", "model_version") if value[key] is None]}


def extract_response(response: Any, built: dict, source_map: dict) -> tuple[list, list, list, dict]:
    """校验全文分片与引文，代码分配观点 ID；完整性不能由模型自报的计数决定。"""
    fields(response, {"batch_id", "execution", "records"}, "extract response")
    require(response["batch_id"] == built["batch_id"], "回复的 batch_id 不匹配")
    provenance = execution(response["execution"], built["prompt_sha256"])
    rows = items(response["records"], "records")
    for row in rows:
        fields(row, {"source_id", "segments"}, "records[]")
    returned = [row["source_id"] for row in rows]
    require(all(isinstance(value, str) for value in returned), "source_id 必须是字符串")
    require(len(returned) == len(set(returned)) and set(returned) == set(built["source_ids"]), f"{built['batch_id']} 有缺失、重复或未知 source_id")
    indexed = {row["source_id"]: row for row in rows}
    observations, retained, coverage = [], [], []
    for source_id in built["source_ids"]:
        source = source_map[source_id]
        segments = items(indexed[source_id]["segments"], source_id + ".segments")
        require(bool(segments), f"{source_id} 没有文本片段")
        for segment in segments:
            fields(segment, {"text", "observations", "retention"}, source_id + ".segment")
            string(segment["text"], "segment.text", empty=True)
        require("".join(part["text"] for part in segments) == source["text"], f"{source_id} 片段未逐字符覆盖源全文，可能遗漏、截断或改写")
        count, retained_count = 0, 0
        for part_index, part in enumerate(segments):
            segment_location = f"{built['batch_id']}.{source_id}.segments[{part_index}]"
            claims = items(part["observations"], segment_location + ".observations")
            require(bool(claims) != (part["retention"] is not None), f"{source_id} 片段须有观点或保留原因，不能同时存在或同时为空")
            if part["retention"] is not None:
                reason = part["retention"]
                fields(reason, {"reason", "note"}, segment_location + ".retention")
                require(reason["reason"] in RETENTIONS, "未知的保留原因")
                string(reason["note"], segment_location + ".retention.note")
                retained.append({"source_id": source_id, "user_id": source["user_id"], "text": part["text"], **reason})
                retained_count += 1
            for claim_index, claim in enumerate(claims):
                location = segment_location + f".observations[{claim_index}]"
                fields(claim, {"statement", "dimension", "stance", "object", "context", "conditions", "quote"}, location)
                for name in ("statement", "quote"):
                    string(claim[name], location + "." + name)
                for name in ("object", "context"):
                    string(claim[name], location + "." + name, empty=True)
                require(claim["dimension"] in DIMENSIONS and claim["stance"] in STANCES, location + " 的 dimension 或 stance 非法")
                for condition in items(claim["conditions"], location + ".conditions"):
                    string(condition, location + ".condition")
                require(claim["quote"] in part["text"], f"{source_id} 引文不在对应片段中，不能引用题干或改写文本")
                count += 1
                observations.append({"id": f"{source_id}.F{count:02d}", "source_id": source_id, "user_id": source["user_id"], "evidence_kind": source["evidence_kind"], **claim})
        coverage.append({"source_id": source_id, "text_characters": len(source["text"]), "segments": len(segments), "observations": count, "retained_segments": retained_count})
    return observations, retained, coverage, provenance


def collect(run: Path) -> dict:
    """汇集完整且对应本次请求的提取文件，生成不截断观点的聚类输入。"""
    manifest, sources = load_run(run)
    require(not (run / "final").exists(), "运行已完成；新分析请新建运行以保留旧结果")
    expected = {batch["id"] + ".json" for batch in manifest["batches"]}
    actual = {file.name for file in (run / "extractions").glob("*.json")}
    require(actual == expected, f"提取回复不齐：缺少 {sorted(expected - actual)}；未知 {sorted(actual - expected)}")
    source_map = {row["source_id"]: row for row in sources["records"]}
    observations, retained, coverage, executions = [], [], [], []
    for batch in manifest["batches"]:
        response_path = run / "extractions" / f"{batch['id']}.json"
        built = read_json(run / "requests" / f"{batch['id']}.json")
        atoms, rest, checked, provenance = extract_response(read_json(response_path), built, source_map)
        observations.extend(atoms)
        retained.extend(rest)
        coverage.extend(checked)
        executions.append({"batch_id": batch["id"], "response_sha256": digest(response_path), **provenance})
    require({row["source_id"] for row in coverage} == set(source_map) and len(coverage) == len(source_map), "批次整体覆盖与源文本清单不一致")
    corpus = {"schema_version": "user_research_observations.v1", "input_sha256": sources["input_sha256"], "observations": observations, "retained_segments": retained, "executions": executions}
    write_json(run / "observations.json", corpus)
    write_json(run / "coverage.json", {"status": "complete", "semantic_coverage": "model_assessed", "source_records": len(source_map), "handled_records": len(coverage), "observations": len(observations), "retained_segments": len(retained), "records": coverage})
    columns = ["id", "user_id", "source_id", "evidence_kind", "dimension", "stance", "object", "statement", "context", "conditions"]
    # 聚类输入仅去掉重复列名和引文副本，statement、条件与所有观点一条不截。
    payload = {"input_sha256": sources["input_sha256"], "users": sources["users"], "profile_source_ids": {user["id"]: [row["source_id"] for row in sources["records"] if row["user_id"] == user["id"] and row["kind"] == "profile"] for user in sources["users"]}, "columns": columns, "rows": [[row[key] for key in columns] for row in observations], "source_index_file": "sources.json", "full_observations_file": "observations.json"}
    built = request("cluster", (run / "prompts/clustering.md").read_text(encoding="utf-8"), payload)
    write_json(run / "cluster-request.json", built)
    write_json(run / "collection.json", {"files": {name: digest(run / name) for name in ("sources.json", "observations.json", "coverage.json", "cluster-request.json")}, "extractions": {item["batch_id"]: item["response_sha256"] for item in executions}})
    return {"status": "complete_text_coverage", "observations": len(observations), "retained_segments": len(retained), "cluster_message_characters": built["message_characters"], "semantic_coverage": "model_assessed"}


def compile_clusters(plan: Any, sources: dict, corpus: dict, prompt_sha256: str) -> dict:
    """聚类覆盖与人数由来源引用派生；背景、避免和条件不能算作正向用户支持。"""
    fields(plan, {"execution", "directions", "user_positioning", "unclustered"}, "cluster response")
    provenance = execution(plan["execution"], prompt_sha256)
    observations = {row["id"]: row for row in corpus["observations"]}
    source_map = {row["source_id"]: row for row in sources["records"]}
    user_map = {user["id"]: user for user in sources["users"]}
    valid = set(observations)
    routes = {key: [] for key in valid}
    feature_used, direction_ids, directions = set(), set(), []

    def referenced(value: Any, label: str, *, empty: bool = True) -> list[str]:
        result = ids(value, valid, label, empty=empty)
        for key in result:
            routes[key].append(label)
        return result

    for direction in items(plan["directions"], "directions"):
        fields(direction, {"id", "name", "design_question", "summary", "features", "context_observation_ids", "differences", "design_implications"}, "direction")
        for name in ("id", "name", "design_question", "summary"):
            string(direction[name], name)
        direction_id = direction["id"]
        require(direction_id not in direction_ids, "方向 ID 重复")
        direction_ids.add(direction_id)
        features = items(direction["features"], "features")
        require(bool(features), f"{direction_id} 没有实际设计特征")
        core = set()
        enriched = []
        for feature in features:
            fields(feature, {"dimension", "stance", "statement", "observation_ids"}, "feature")
            string(feature["statement"], "feature.statement")
            require(feature["dimension"] in DIMENSIONS and feature["stance"] in STANCES, "特征 dimension 或 stance 非法")
            selected = referenced(feature["observation_ids"], direction_id + ".features", empty=False)
            require(all(observations[key]["dimension"] == feature["dimension"] and observations[key]["stance"] == feature["stance"] for key in selected), "特征不能改变原观点维度或把 avoid/conditional 变成 prefer；请拆分特征")
            core.update(selected)
            feature_used.update(selected)
            enriched.append({**feature, "observations": [observations[key] for key in selected]})
        referenced(direction["context_observation_ids"], direction_id + ".context")
        for difference in items(direction["differences"], "differences"):
            fields(difference, {"description", "observation_ids"}, "difference")
            string(difference["description"], "difference.description")
            ids(difference["observation_ids"], valid, direction_id + ".differences", empty=False)
        proposals = []
        for suggestion in items(direction["design_implications"], "design_implications"):
            fields(suggestion, {"proposal", "observation_ids"}, "design_implication")
            string(suggestion["proposal"], "proposal")
            # 建议和差异的引用不能单独充当源观点的最终归属。
            ids(suggestion["observation_ids"], valid, direction_id + ".proposal", empty=False)
            proposals.append({"status": "proposal", **suggestion})
        directions.append({**direction, "features": enriched, "design_implications": proposals, "users_by_stance": {stance: sorted({observations[key]["user_id"] for key in core if observations[key]["stance"] == stance}) for stance in sorted(STANCES)}, "sample_user_count": len(user_map), "source_ids": sorted({observations[key]["source_id"] for key in core})})

    positioning, positioned = [], set()
    for row in items(plan["user_positioning"], "user_positioning"):
        fields(row, {"user_id", "summary", "source_ids", "observation_ids"}, "user_positioning[]")
        uid = row["user_id"]
        require(uid in user_map and uid not in positioned, "用户定位有重复或未知用户")
        positioned.add(uid)
        string(row["summary"], "positioning.summary")
        selected = referenced(row["observation_ids"], uid + ".positioning")
        source_ids = ids(row["source_ids"], set(source_map), uid + ".source_ids")
        require(bool(source_ids or selected), "定位摘要必须有该用户的文本来源")
        require(all(observations[key]["user_id"] == uid for key in selected) and all(source_map[key]["user_id"] == uid for key in source_ids), "用户定位不能引用其他用户的资料")
        positioning.append({**row, "name": user_map[uid]["name"], "profile": user_map[uid]["profile"]})
    require(positioned == set(user_map), f"缺少用户定位：{sorted(set(user_map) - positioned)}")
    unclustered_ids = set()
    for row in items(plan["unclustered"], "unclustered"):
        fields(row, {"observation_id", "note"}, "unclustered[]")
        selected = ids([row["observation_id"]], valid, "unclustered")
        require(selected[0] not in unclustered_ids, "未聚类观点重复")
        require(not routes[selected[0]], "已有明确归属的观点不能同时标为未聚类")
        unclustered_ids.add(selected[0])
        routes[selected[0]].append("unclustered")
        string(row["note"], "unclustered.note")
        require(observations[selected[0]]["dimension"] in CONTEXT_DIMENSIONS, "不能将审美设计观点丢入未聚类项；单人偏好也需形成方向")
    missing_design = {key for key, value in observations.items() if value["dimension"] not in CONTEXT_DIMENSIONS} - feature_used
    require(not missing_design, f"设计观点未进入方向特征：{sorted(missing_design)}")
    require(all(routes.values()), f"存在无去向观点：{sorted(key for key, value in routes.items() if not value)}")
    return {"schema_version": "user_research_design_clusters.v1", "skill_version": VERSION, "input_sha256": sources["input_sha256"], "image_analysis_performed": False, "coverage_status": "complete", "semantic_coverage": "model_assessed", "directions": directions, "user_positioning": positioning, "unclustered": plan["unclustered"], "observation_routes": routes, "execution": provenance, "extraction_executions": corpus["executions"], "status": "completed" if directions else "no_design_evidence"}


def render_report(result: dict) -> str:
    lines = ["# 用户调研审美设计方向", "", f"{len(result['user_positioning'])} 位用户 · {len(result['directions'])} 个方向 · 文本和观点去向覆盖完整。", "", "语义由模型逐项整理；结构覆盖不等于独立语义审计。", "", "完整资料：[源文本](../sources.json) · [全部观点与保留片段](../observations.json) · [覆盖清单](../coverage.json) · [结构结果](result.json) · [趋势匹配输入](handshake.json)", ""]
    for direction in result["directions"]:
        lines.extend([f"## {direction['id']} {direction['name']}", "", direction["design_question"], "", direction["summary"], ""])
        for feature in direction["features"]:
            lines.append(f"- [{feature['dimension']} / {feature['stance']}] {feature['statement']}（{', '.join(feature['observation_ids'])}）")
        lines.extend(["", "样本用户按态度去重：" + "；".join(f"{key}: {', '.join(value) or '无'}" for key, value in direction["users_by_stance"].items()), ""])
        for difference in direction["differences"]:
            lines.append(f"- 差异：{difference['description']}（{', '.join(difference['observation_ids'])}）")
        for suggestion in direction["design_implications"]:
            lines.append(f"- 推导建议：{suggestion['proposal']}（{', '.join(suggestion['observation_ids'])}）")
        lines.append("")
    lines.extend(["## 用户定位", ""])
    for user in result["user_positioning"]:
        lines.extend([f"### {user['name'] or user['user_id']}（{user['user_id']}）", "", user["summary"], "", f"来源：{', '.join(user['source_ids'] + user['observation_ids'])}", ""])
    if result["unclustered"]:
        lines.extend(["## 保留背景观点", ""])
        lines.extend(f"- {row['observation_id']}：{row['note']}" for row in result["unclustered"])
    gaps = [row for row in result["extraction_executions"] + [result["execution"]] if row["traceability_gaps"]]
    if gaps:
        lines.extend(["", f"模型追溯缺项：{len(gaps)} 次执行未提供完整模型标识/版本，详情见 result.json。"])
    return "\n".join(lines) + "\n"


def finalize(run: Path, cluster_path: Path) -> dict:
    """检查观点去向后一次发布新结果，最终目录只代表完整编译成功。"""
    _, sources = load_run(run)
    collection = read_json(run / "collection.json")
    for name, expected in collection["files"].items():
        require(digest(run / name) == expected, f"{name} 已变化，请重新 collect 后聚类")
    for name, expected in collection["extractions"].items():
        require(digest(run / "extractions" / f"{name}.json") == expected, f"提取 {name} 已变化，请重新 collect 后聚类")
    result = compile_clusters(read_json(cluster_path), sources, read_json(run / "observations.json"), read_json(run / "cluster-request.json")["prompt_sha256"])
    final = run / "final"
    require(not final.exists(), "final 已存在，请保留旧结果并新建运行")
    result.update({"sources_file": "../sources.json", "observations_file": "../observations.json", "coverage_file": "../coverage.json", "cluster_response_sha256": digest(cluster_path), "compiled_at": datetime.now(timezone.utc).isoformat()})
    # 先在本运行内写齐派生文件，再原子发布目录；写盘中断不会留下貌似完成的 final。
    with tempfile.TemporaryDirectory(prefix=".final-", dir=run) as folder:
        staging = Path(folder)
        write_json(staging / "result.json", result)
        write_json(staging / "handshake.json", {"schema_version": "user_research_design_handshake.v1", "stage": "research_only", "ready_for_handshake": bool(result["directions"]), "input_sha256": result["input_sha256"], "coverage_status": result["coverage_status"], "semantic_coverage": result["semantic_coverage"], "image_analysis_performed": False, "directions": result["directions"], "user_positioning": result["user_positioning"], "sources_file": "../sources.json", "observations_file": "../observations.json", "full_result_file": "result.json"})
        (staging / "report.md").write_text(render_report(result), encoding="utf-8")
        staging.rename(final)
    return {"status": result["status"], "directions": len(result["directions"]), "result_dir": str(final.resolve())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--input", type=Path, default=Path("data/userreseach_data/users_selected_5.json"))
    prep.add_argument("--out", type=Path)
    prep.add_argument("--max-chars", type=int, default=48000)
    prep.add_argument("--dry-run", action="store_true")
    gather = commands.add_parser("collect")
    gather.add_argument("--run", type=Path, required=True)
    finish = commands.add_parser("finalize")
    finish.add_argument("--run", type=Path, required=True)
    finish.add_argument("--clusters", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.input, args.out, args.max_chars, args.dry_run)
        elif args.command == "collect":
            result = collect(args.run)
        else:
            result = finalize(args.run, args.clusters)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"错误：{error}\n")


if __name__ == "__main__":
    main()

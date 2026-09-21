"""轻量流程的原始来源索引与按字符预算合包；只依赖标准库。"""

from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

from contracts import image_code_in_text
from core import release_date
from prepare import image_ref, required_id, text_value
from lean_images import is_positive_user_image, linked_image_refs, selected_user_images


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _has_text(value):
    # 0 和 false 可以是完整回答；仅排除缺失、空容器和纯空白文本。
    return value is not None and value != [] and value != {} and (
        not isinstance(value, str) or bool(value.strip()))


def _rows(document, key):
    rows = document.get(key, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{key} 必须为对象数组")
    return rows


def build_sources(trends_path, users_path, project_root, start_date=None, end_date=None,
                  undated="exclude", user_limit=None):
    """从原文件建立短 ID 索引；日期包含两端，用户前 N 按原数组完整对象选取。

    ``sources`` 的键是 T00001 / U000001，值中的 ``id`` 和 ``source_id``
    保留原记录身份；所有 JSON 指针均指向 ``inputs`` 中的原文件。
    """
    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None
    if start and end and start > end:
        raise ValueError("开始日期不能晚于结束日期")
    if undated not in {"exclude", "include"}:
        raise ValueError("undated 必须是 exclude 或 include")
    if user_limit is not None and (type(user_limit) is not int or user_limit < 1):
        raise ValueError("user_limit 必须为正整数或 None")

    paths = {"trends": Path(trends_path).resolve(), "users": Path(users_path).resolve()}
    project_trend_root = (Path(project_root).resolve() / "data/trend_data").resolve()
    # 新版索引位于 article_table_2，图片统一放在其同级公共 images 目录。
    trend_image_boundary = (project_trend_root if paths["trends"].is_relative_to(project_trend_root)
                            else paths["trends"].parent)
    raw = {side: path.read_bytes() for side, path in paths.items()}
    documents = {side: json.loads(content) for side, content in raw.items()}
    if any(not isinstance(document, dict) for document in documents.values()):
        raise ValueError("来源文件必须为 JSON 对象")
    trends = _rows(documents["trends"], "trends")
    users = _rows(documents["users"], "users")
    sources, seen_records, excluded = {}, set(), Counter()
    trend_ids, user_ids, text_users = set(), [], set()
    trend_count, user_count, undated_count = 0, 0, 0

    def add(alias, record):
        if record["id"] in seen_records:
            raise ValueError(f"重复记录 ID：{record['id']}")
        seen_records.add(record["id"])
        sources[alias] = record

    for index, row in enumerate(trends):
        identifier = required_id(row)
        if identifier in trend_ids:
            raise ValueError(f"重复趋势 ID：{identifier}")
        trend_ids.add(identifier)
        try:
            day = release_date(row.get("release_time"))
        except ValueError as exc:
            raise ValueError(f"趋势 {identifier} 的发布日期非法") from exc
        if day is None:
            undated_count += 1
            if undated == "exclude":
                excluded["undated"] += 1
                continue
        elif (start and day < start) or (end and day > end):
            excluded["outside_range"] += 1
            continue
        rid = f"trend:{identifier}"
        trend_count += 1
        add(f"T{trend_count:05d}", {
            "id": rid, "kind": "trend", "source_id": identifier,
            "fields": {key: text_value(row[key]) for key in (
                "title_zh", "summary_zh", "primary_category", "subcategory", "tags")
                if row.get(key) is not None},
            "release_time": day.isoformat() if day else None,
            "clustering_label": (text_value(row["clustering_label"]).strip()
                                 if row.get("clustering_label") is not None else "") or "未分类",
            "source_file": "trends", "json_pointer": f"/trends/{index}",
            "image_refs": [image_ref(image, paths["trends"].parent, rid,
                                     allowed_root=trend_image_boundary)
                           for image in row.get("images", [])],
        })

    selected_users = users if user_limit is None else users[:user_limit]
    for index, row in enumerate(selected_users):
        uid = required_id(row)
        if uid in user_ids:
            raise ValueError(f"重复用户 ID：{uid}")
        user_ids.append(uid)
        preferences = {}
        for preference in row.get("image_preferences", []):
            code = preference.get("ref_pic_code")
            if code and is_positive_user_image(preference):
                preferences.setdefault(code, []).append(image_ref(
                    preference, paths["users"].parent, f"user:{uid}", code,
                    preference.get("emotion_tag")))
        for key, kind, answer_key, field_names in (
            ("aesthetic_research", "user_qa", "ai_analysis",
             ("question", "ai_analysis", "answer_type", "scenario_type", "question_type")),
            ("demand_research", "user_demand", "ai_index", ("ai_index", "scenario", "ref_pic")),
        ):
            for child_index, child in enumerate(_rows(row, key)):
                answer = child.get(answer_key)
                if not _has_text(answer):
                    excluded["empty_qa" if kind == "user_qa" else "empty_demand"] += 1
                    continue
                if kind == "user_qa" and "未提及" in text_value(answer):
                    excluded["unmentioned_qa"] += 1
                    continue
                cid = required_id(child)
                rid = f"user:{uid}:{kind}:{cid}"
                fields = {name: text_value(child[name]) for name in field_names
                          if child.get(name) is not None}
                images = []
                if kind == "user_qa":
                    # 问答只关联回答中实际出现且明确 LIKE / ENJOY 的图片编码。
                    images = [ref for code, group in preferences.items()
                              if image_code_in_text(code, fields[answer_key]) for ref in group]
                # 显式本地链接不要求复述编号，但同样必须明确标记 LIKE / ENJOY。
                images.extend(linked_image_refs(child, paths["users"].parent, rid))
                user_count += 1
                add(f"U{user_count:06d}", {
                    "id": rid, "kind": kind, "source_id": cid, "user_id": uid,
                    "profile": row.get("profile", {}), "fields": fields,
                    "source_file": "users", "json_pointer": f"/users/{index}/{key}/{child_index}",
                    "image_refs": images,
                })
                text_users.add(uid)

    orphan_count = len(_rows(documents["users"], "unlinked_demand_research"))
    categories = {}
    for alias, record in sources.items():
        if record["kind"] == "trend":
            categories.setdefault(record["clustering_label"], []).append(alias)
    return {
        "project_root": str(Path(project_root).resolve()),
        "sources": sources,
        "user_image_inventory": selected_user_images(selected_users, paths["users"].parent),
        "trend_categories": [{"label": label, "source_ids": ids, "article_count": len(ids)}
                             for label, ids in categories.items()],
        "inputs": {side: {"path": str(path), "sha256": hashlib.sha256(raw[side]).hexdigest()}
                   for side, path in paths.items()},
        "selection": {"start_date": start_date, "end_date": end_date, "inclusive": True,
                      "undated_policy": undated, "undated_in_source": undated_count,
                      "user_limit": user_limit, "selected_user_ids": user_ids,
                      "excluded": dict(excluded)},
        "counts": {"source_trends": len(trends), "selected_trends": trend_count,
                   "source_users": len(users), "selected_users": len(selected_users),
                   "users": len(selected_users), "users_with_text": len(text_users),
                   "source_records": len(sources), "trend_records": trend_count,
                   "user_records": user_count, "excluded_unmentioned_qa": excluded["unmentioned_qa"],
                   "excluded_empty_qa": excluded["empty_qa"],
                   "excluded_empty_demand": excluded["empty_demand"],
                   "excluded_unlinked_demands": orphan_count,
                   "excluded_users_by_limit": len(users) - len(selected_users)},
    }


def _pack_text(side, items):
    if side == "trend":
        trends = []
        for alias, record in items:
            fields = record["fields"]
            row = {"id": alias, "date": record.get("release_time")}
            for original, compact in (("title_zh", "title"), ("summary_zh", "summary"),
                                      ("primary_category", "category"), ("subcategory", "subcategory"),
                                      ("tags", "tags")):
                if original in fields:
                    row[compact] = fields[original]
            trends.append(row)
        return _compact({"clustering_label": items[0][1].get("clustering_label", "未分类"), "trends": trends})

    contexts, context_ids, profiles, rows = {}, {}, {}, []
    for alias, record in items:
        uid, fields, kind = record["user_id"], record["fields"], record["kind"]
        profile = record.get("profile", {})
        if uid in profiles and profiles[uid] != profile:
            raise ValueError(f"用户 {uid} 的画像不一致")
        profiles[uid] = profile
        context_key = "question" if kind == "user_qa" else "scenario"
        answer_key = "ai_analysis" if kind == "user_qa" else "ai_index"
        context = {"kind": kind, context_key: fields.get(context_key, "")}
        signature = _compact(context)
        if signature not in context_ids:
            cid = f"C{len(contexts) + 1:03d}"
            context_ids[signature] = cid
            contexts[cid] = context
        rows.append([alias, uid, context_ids[signature], fields[answer_key]])
    return _compact({"contexts": contexts, "profiles": profiles, "rows": rows})


def pack_sources(sources, max_chars):
    """趋势先按聚类标签归组，类内按字符分包；用户材料单独去重合包，供各类共享。

    问题、需求场景和画像在包内去重，回答全文保留。路径和图片引用只存
    在来源索引，不进入模型文本。单条连同必要上下文超预算时明确报错。
    """
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars 必须为正整数")
    trend_groups, user_items = {}, []
    for alias, record in sources.items():
        kind = record["kind"]
        if kind not in {"trend", "user_qa", "user_demand"}:
            raise ValueError(f"来源 {alias} 的类型不受支持：{kind}")
        if kind == "trend":
            label = record.get("clustering_label", "未分类")
            trend_groups.setdefault(label, []).append((alias, record))
        else:
            user_items.append((alias, record))

    packs = []
    # 同类文章即使在原文件中不相邻，也先合在一起；不同大类绝不混进归纳包。
    partitions = [("trend", label, items) for label, items in trend_groups.items()]
    partitions.append(("user", None, user_items))
    for side, label, items in partitions:
        current, current_text = [], ""
        for item in items:
            candidate = current + [item]
            text = _pack_text(side, candidate)
            if current and len(text) > max_chars:
                packs.append({"side": side, "clustering_label": label, "text": current_text,
                              "source_ids": [alias for alias, _ in current]})
                candidate = [item]
                text = _pack_text(side, candidate)
            if len(text) > max_chars:
                raise ValueError(f"单条来源 {item[0]} 连同上下文需要 {len(text)} 字符，"
                                 f"超过预算 {max_chars}；请增大字符预算，原文不会截断")
            current, current_text = candidate, text
        if current:
            packs.append({"side": side, "clustering_label": label, "text": current_text,
                          "source_ids": [alias for alias, _ in current]})
    return packs

"""把宽松 Markdown 归纳直接编译为可追溯产物，不审核语义或触发模型重试。"""

from __future__ import annotations

from pathlib import Path
import re

from core import atomic_text, encode, timestamp, write
from reporting import resolve_images


HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
REFERENCE = re.compile(r"(?<![A-Za-z0-9_])[TUN]\d+(?![A-Za-z0-9_])")
GAP_TITLE = re.compile(r"用研补充|用户补充|用研多数人提及")
FORBIDDEN_TITLE = re.compile(r"下一轮验证|validation_questions", re.IGNORECASE)
USER_KINDS = {"user_qa", "user_demand"}
COUNT_NOTE = "人数是正文已引用来源中去重用户的提及下限，包含不同态度，不是共同偏好率或市场占比。"
GAP_SCOPE = "缺乏趋势覆盖是模型对所读文本的摘要判断，未执行逐篇原文覆盖审核，不代表市场空白。"
SOURCE_SCOPE = "只关联正文实际引用且来源索引中存在的记录；未执行全量来源覆盖或额外语义审核。"


def _clean_markdown(text):
    lines, removed, skip_level = [], 0, None
    for line in text.replace("\ufeff", "").splitlines():
        # 外层 Markdown 围栏不是研究正文；保留围栏中的实际文字与三级标题。
        if re.fullmatch(r"\s*(?:`{3,}|~{3,})[^`~]*", line):
            continue
        heading = HEADING.match(line)
        level = len(heading[1]) if heading else None
        if skip_level is not None:
            if level is None or level > skip_level:
                continue
            skip_level = None
        if heading and FORBIDDEN_TITLE.search(heading[2]):
            skip_level = level
            removed += 1
            continue
        lines.append(line)
    warnings = [f"已移除 {removed} 段旧版验证建议，保留其他正文。"] if removed else []
    return "\n".join(lines).strip(), warnings


def _source_ids(text, sources, aliases, warnings):
    found = []
    for token in REFERENCE.findall(text):
        ids = [token] if token in sources else aliases.get(token)
        if ids is None:
            warnings.append(f"未知引用 {token}：保留正文，忽略其来源关联。")
            continue
        for source_id in ids:
            if source_id not in sources:
                warnings.append(f"未知引用 {source_id}（来自 {token}）：忽略其来源关联。")
            elif source_id not in found:
                found.append(source_id)
    return found


def parse_notes(text, sources, aliases=None):
    """按二级标题拆方向；一级标题只标分区，缺少二级标题时完整保留为一份摘要。

    sources 的键为 T/U 短来源 ID，aliases 可把 N 摘要编号映射回多个已有来源。
    返回的 warnings 只提示关联缺口，不构成格式拒绝或重试条件。
    """
    cleaned, warnings = _clean_markdown(text)
    if not cleaned:
        return [], warnings
    aliases = aliases or {}
    lines = cleaned.splitlines()
    has_sections = any((match := HEADING.match(line)) and len(match[1]) == 2 for line in lines)
    notes = []

    def add(title, body, section=""):
        content = "\n".join(body).strip()
        if not title and not content:
            return
        title = title or "摘要"
        notes.append({"title": title, "text": content,
                      "source_ids": _source_ids(title + "\n" + content, sources, aliases, warnings),
                      "kind": "user_gap" if GAP_TITLE.search(section + "\n" + title) else "idea"})

    if not has_sections:
        headings = [match[2] for line in lines if (match := HEADING.match(line)) and len(match[1]) == 1]
        add(headings[0] if headings else "摘要", lines, "\n".join(headings))
    else:
        title, section, body = None, "", []
        for line in lines:
            heading = HEADING.match(line)
            level = len(heading[1]) if heading else None
            if level in {1, 2}:
                add(title, body, section)
                body = []
                if level == 1:
                    section, title = heading[2], None
                else:
                    title = heading[2]
            else:
                body.append(line)
        add(title, body, section)
    return notes, list(dict.fromkeys(warnings))


def _original_text(record):
    fields = record.get("fields", {})
    field = {"trend": "summary_zh", "user_qa": "ai_analysis"}.get(record.get("kind"), "ai_index")
    value = fields.get(field, "")
    return value if isinstance(value, str) else encode(value)


def _code_mentioned(text, code):
    """图片编码必须作为独立编号出现在用户原回答中，避免把题干图片误算为用户提及。"""
    return bool(isinstance(code, str) and code and re.search(
        r"(?<![A-Za-z0-9])" + re.escape(code) + r"(?![A-Za-z0-9])", text))


def _source_record(short_id, record, manifest):
    # 交付JSON只带定位信息，原文保留在sources.json；避免每张卡重复拷贝整段问答。
    source = {"short_id": short_id, "record_id": record['id'], "kind": record['kind'],
              "user_id": record.get('user_id'), "source_file": record.get('source_file'),
              "json_pointer": record.get('json_pointer'), "title": record.get('fields', {}).get('title_zh')}
    input_file = manifest.get("inputs", {}).get(record.get("source_file"), {})
    source["source_path"] = input_file.get("path") if isinstance(input_file, dict) else input_file
    return source


def _images(ids, sources, project_root, warnings):
    evidence, records = [], {}
    for short_id in ids:
        record = sources[short_id]
        records[record["id"]] = record
        original = _original_text(record)
        # 编码只从当前源记录的图库取，并要求原回答明确出现；问题与模型正文均不能补编码。
        codes = list(dict.fromkeys(ref["code"] for ref in record.get("image_refs", [])
                                   if _code_mentioned(original, ref.get("code"))))
        evidence.append({"id": short_id, "record_id": record["id"], "kind": record["kind"],
                         "relation": "mention", "image_codes": codes})
    refs = resolve_images(evidence, records, project_root)
    for ref in refs:
        if not ref["file_exists"]:
            # 缺失文件不作为可用路径交付，仍保留来源声明路径以便人工排查。
            ref["declared_path"] = ref["absolute_path"]
            ref["path"] = ref["absolute_path"] = None
            warnings.append(f"来源 {ref['source_record_id']} 的图片 {ref['image_id'] or ref['code'] or '未编号'} 不可用，路径置空。")
    return refs


def _ref_path(ref, project_root):
    """兼容最终引用与原始来源引用，统一返回规范化绝对路径。"""
    value = ref.get("absolute_path") or ref.get("declared_path")
    if value is None and ref.get("local_path"):
        value = Path(ref.get("source_root") or project_root) / ref["local_path"]
    if value is None:
        return None
    path = Path(value)
    return (path if path.is_absolute() else project_root / path).resolve()


def _append_image(entries, by_path, ref, project_root, *, source_id=None, result=None):
    path = _ref_path(ref, project_root)
    if path is None:
        return
    key = str(path)
    entry = by_path.get(key)
    if entry is None:
        entry = {"path": key, "file_exists": path.is_file(), "image_ids": [], "codes": [],
                 "source_record_ids": [], "results": []}
        by_path[key] = entry
        entries.append(entry)
    for field, value in (("image_ids", ref.get("image_id")), ("codes", ref.get("code")),
                         ("source_record_ids", source_id or ref.get("source_record_id")),
                         ("results", result)):
        value = str(value) if value is not None else None
        if value and value not in entry[field]:
            entry[field].append(value)


def _image_path_report(items, sources, project_root):
    """生成两段去重路径：最终结果关联图片，以及其余用户明确提及图片。"""
    result_images, result_by_path = [], {}
    for item in items:
        result_label = f"{item['id']} {item['title']}"
        for ref in item.get("image_refs", []):
            _append_image(result_images, result_by_path, ref, project_root, result=result_label)

    user_images, user_by_path = [], {}
    for short_id, record in sources.items():
        if record.get("kind") not in USER_KINDS:
            continue
        original = _original_text(record)
        for ref in record.get("image_refs", []):
            # user_qa 只认回答中明确出现的编码；user_demand 的 ref_pic_links 本身就是直接关联。
            if record.get("kind") == "user_qa" and not _code_mentioned(original, ref.get("code")):
                continue
            path = _ref_path(ref, project_root)
            if path is None or str(path) in result_by_path:
                continue
            _append_image(user_images, user_by_path, ref, project_root,
                          source_id=f"{short_id} / {record['id']}")

    def render(entries, empty_text):
        if not entries:
            return [empty_text]
        lines = []
        for entry in entries:
            details = []
            if entry["image_ids"]:
                details.append("图片 ID：" + "、".join(entry["image_ids"]))
            if entry["codes"]:
                details.append("图片编码：" + "、".join(entry["codes"]))
            if entry["results"]:
                details.append("关联结果：" + "；".join(entry["results"]))
            if entry["source_record_ids"]:
                details.append("来源记录：" + "；".join(entry["source_record_ids"]))
            if not entry["file_exists"]:
                details.append("文件不存在")
            suffix = " — " + "；".join(details) if details else ""
            lines.append(f"- [打开图片](<{entry['path']}>) `{entry['path']}`{suffix}")
        return lines

    lines = ["# 图片路径汇总", "",
             "仅汇总来源索引中的既有路径，按规范化绝对路径去重；图片未被读取或视觉核验。", "",
             "## 与结果相关的所有图片路径", "",
             f"共 {len(result_images)} 条去重路径。", ""]
    lines += render(result_images, "本轮结果没有可关联的图片路径。")
    lines += ["", "## 用户提及的其他图片路径", "",
              "以下路径来自全部入选用户来源，并已排除第一部分出现的路径。", "",
              f"共 {len(user_images)} 条去重路径。", ""]
    lines += render(user_images, "没有与第一部分去重后剩余的用户提及图片路径。")
    return "\n".join(lines) + "\n", {
        "result_image_paths": len(result_images),
        "additional_user_image_paths": len(user_images),
    }


def _population(manifest, sources, warnings):
    counts = manifest.get("counts", {})
    for key in ("users_with_text", "users"):
        value = counts.get(key)
        if type(value) is int and value >= 0:
            return value
    warnings.append("manifest 未提供用户分母，使用来源索引中全部可归属用户的去重人数。")
    return len({record["user_id"] for record in sources.values()
                if record.get("kind") in USER_KINDS and record.get("user_id") is not None})


def _render_item(item):
    lines = [f"## {item['title']}", "", item["description"], ""]
    stats = item["mention_statistics"]
    lines += [f"已引用去重用户：{stats['unique_mentioned_users']}/{stats['population_count']}；{COUNT_NOTE}", ""]
    if item["image_refs"]:
        lines.append("来源关联图片（未做视觉核验）：")
        for ref in item["image_refs"]:
            label = str(ref["image_id"] or ref["code"] or "未编号图片")
            lines.append(f"- [{label}](<{ref['absolute_path']}>)" if ref["absolute_path"] else f"- {label}：图片缺失，路径为空。")
        lines.append("")
    else:
        lines += ["当前引用没有可关联图片。", ""]
    lines.append("来源编号：" + "、".join(source['short_id'] for source in item['source_records']) + "；完整原文保存在同目录 sources.json。")
    return lines


def publish(run, manifest, sources, text, aliases=None, execution=None, image_sources=None):
    """确定性发布宽松正文、已有来源与统计；自由正文可交付，空内容如实标记为空。"""
    run = Path(run)
    project_root = Path(manifest["project_root"]).resolve()
    notes, warnings = parse_notes(text, sources, aliases)
    warnings.extend((execution or {}).get('warnings', []))
    population = _population(manifest, sources, warnings)
    cards, gaps, diagnostics, unlinked = [], [], [], []
    for index, note in enumerate(notes, 1):
        ids = note["source_ids"]
        if not ids:
            unlinked.append(note)
            continue
        users = sorted({sources[sid]["user_id"] for sid in ids
                        if sources[sid].get("kind") in USER_KINDS and sources[sid].get("user_id") is not None}, key=str)
        has_trends = any(sources[sid].get("kind") == "trend" for sid in ids)
        item = {"id": f"D{index:04d}", "title": note["title"], "description": note["text"],
                "kind": note["kind"], "source_ids": ids,
                "source_records": [_source_record(sid, sources[sid], manifest) for sid in ids],
                "image_refs": _images(ids, sources, project_root, warnings), "cited_user_ids": users,
                "mention_statistics": {"unique_mentioned_users": len(users), "population_count": population,
                                       "count_type": "cited_mentions_lower_bound", "note": COUNT_NOTE},
                "human_review_status": "pending"}
        if has_trends and users:
            cards.append(item)
        elif note["kind"] == "user_gap" and not has_trends and users and population > 0 and len(users) * 2 > population:
            item["mention_statistics"]["majority"] = True
            item["trend_coverage_note"] = GAP_SCOPE
            gaps.append(item)
        else:
            item["reason"] = ("用户补充方向的已引用去重人数未严格超过分母一半。"
                              if note["kind"] == "user_gap" and not has_trends and users
                              else "当前引用未组成趋势与可归属用户的双侧方向。")
            diagnostics.append(item)
    if unlinked:
        warnings.append(f"有 {len(unlinked)} 段正文未关联有效来源，已保留为未关联笔记。")
    # 单独的标题或空围栏不是研究正文；仍保留原笔记供人工查看。
    has_content = any(line.strip() and not HEADING.match(line)
                      for note in notes for line in note["text"].splitlines())
    if not has_content:
        warnings.append("本轮没有可交付的研究正文，不能视为完成研究。")
    warnings = list(dict.fromkeys(warnings))
    partial = bool(unlinked) or bool((execution or {}).get('partial')) or any(warning.startswith("未知引用") for warning in warnings)
    generated = timestamp()
    gap_section = {"status": "compiled", "population_count": population, "directions": gaps,
                   "scope_note": GAP_SCOPE, "count_note": COUNT_NOTE}
    # 综合任务只携带实际进入笔记的来源；独立图片清单仍需扫描本轮完整用户来源。
    image_path_text, image_path_counts = _image_path_report(
        cards + gaps, sources if image_sources is None else image_sources, project_root)
    document = {"schema_version": "design_trend_insights_v3", "generated_at": generated,
                "selection": manifest.get("selection", {}), "input_counts": manifest.get("counts", {}),
                "source_inputs": manifest.get("inputs", {}), "trends": cards, "user_research_gaps": gap_section,
                "diagnostics": diagnostics, "unlinked_notes": unlinked, "execution": execution,
                "source_index_file": "sources.json", "image_path_report_file": "image_paths.md",
                "scope_note": SOURCE_SCOPE,
                "warnings": warnings, "has_content": has_content, "partial": partial}
    summary = {"status": "empty" if not has_content else "partial" if partial else "complete",
               "has_content": has_content, "partial": partial, "completed_at": generated,
               "trends": len(cards), "user_research_gaps": len(gaps), "diagnostics": len(diagnostics),
               "unlinked_notes": len(unlinked), "warnings": warnings, "source_scope": SOURCE_SCOPE,
               "report": str((run / "report.md").resolve()),
               "image_paths": str((run / "image_paths.md").resolve())}
    validation = {**summary, "checks": "仅核对已知引用、去重人数和图片文件是否存在。", "semantic_review": "not_performed",
                  "image_reference_count": sum(len(item["image_refs"]) for item in cards + gaps + diagnostics),
                  "missing_image_references": sum(not ref["file_exists"] for item in cards + gaps + diagnostics for ref in item["image_refs"]),
                  **image_path_counts}
    selection = manifest.get("selection", {})
    lines = ["# 通用设计趋势洞察", "", SOURCE_SCOPE, "", COUNT_NOTE, "",
             f"趋势日期范围：{selection.get('start_date') or '不限'} 至 {selection.get('end_date') or '不限'}；用户文本不按趋势日期过滤。",
             f"本轮纳入趋势 {manifest.get('counts', {}).get('selected_trends', 0)} 条；用户统计分母 {population} 人。", ""]
    if not has_content:
        lines += ["本轮没有可交付的研究正文。", ""]
    lines += ["# 趋势与用户共同方向", ""]
    for card in cards:
        lines.extend(_render_item(card))
    if not cards:
        lines += ["本轮未形成同时关联趋势与用户来源的主方向。", ""]
    lines += ["# 用研补充", "", GAP_SCOPE, ""]
    for gap in gaps:
        lines.extend(_render_item(gap))
    if not gaps:
        lines += ["本轮没有已引用去重人数严格超过分母一半的用户补充方向。", ""]
    if unlinked:
        lines += ["# 未关联笔记", "", "以下正文保留原意，但有效来源关联不全。", ""]
        for note in unlinked:
            lines += [f"## {note['title']}", "", note["text"], ""]
    if warnings:
        lines += ["# 编译提示", ""] + [f"- {warning}" for warning in warnings]
    write(run / "high_potential_trends.json", document)
    if not (run / 'sources.json').exists():
        write(run / 'sources.json', sources if image_sources is None else image_sources)
    atomic_text(run / "high_potential_trends.jsonl", "".join(encode(card) + "\n" for card in cards))
    atomic_text(run / "report.md", "\n".join(lines) + "\n")
    atomic_text(run / "image_paths.md", image_path_text)
    write(run / "validation_report.json", validation)
    # 完成文件最后写入；调用方仍须检查 has_content，不能把文件存在等同于研究成功。
    write(run / "completion.json", summary)
    return summary

"""纯文本趋势聚类的冻结、复核和编译；不调用模型，不读取图片。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

VERSION = "3.0.0"
THEME_FIELDS = ("theme_id", "title", "definition", "boundary", "design_question")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _required(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空文本")
    return value.strip()


def _canonical_url(value):
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"),
                       urlencode(sorted(query)), parts.fragment))


def normalize_records(rows):
    """白名单整理文章；明确来源组、同文 URL、相同文本按连通关系去重。"""
    records, seen, parents, keys = [], set(), {}, {}

    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for row in rows:
        raw_id = row.get("article_id", row.get("id"))
        article_id = str(raw_id).strip() if raw_id is not None else ""
        if not article_id or article_id in seen:
            raise ValueError(f"文章 ID 缺失或重复：{article_id}")
        seen.add(article_id)
        parents[article_id] = article_id
        title = str(row.get("title") or row.get("title_zh") or "").strip()
        summary = str(row.get("summary") or row.get("summary_zh") or "").strip()
        text = "\n".join(value for value in (title, summary) if value)
        source_url = str(row.get("detail_url") or row.get("source_url") or "").strip()
        record = {"article_id": article_id, "title": title, "summary": summary,
                  "text": text, "text_hash": _digest(text), "source_url": source_url,
                  "text_kind": str(row.get("text_kind") or "source_paraphrase"),
                  "published_at": str(row.get("published_at") or "")}
        group_keys = []
        if row.get("source_group_id"):
            group_keys.append("explicit:" + str(row["source_group_id"]))
        if canonical := _canonical_url(source_url):
            group_keys.append("url:" + canonical)
        if text:
            normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
            group_keys.append("text:" + _digest(normalized))
        for key in group_keys:
            if key in keys:
                left, right = find(article_id), find(keys[key])
                parents[max(left, right)] = min(left, right)
            else:
                keys[key] = article_id
        records.append(record)
    for record in records:
        record["source_group_id"] = "sg_" + _digest(find(record["article_id"]))[:20]
    return records


def _pack(items, max_chars):
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 128:
        raise ValueError("max_chars 必须为至少 128 的整数")
    packets, current, size = [], [], 2
    for item in items:
        item_size = len(_json(item))
        if item_size + 2 > max_chars:
            raise ValueError(f"单条文本超出分包预算，不能静默截断：{item.get('article_id')}")
        if current and size + item_size + 1 > max_chars:
            packets.append(current)
            current, size = [], 2
        size += item_size + (1 if current else 0)
        current.append(item)
    if current:
        packets.append(current)
    return packets


def pack_records(records, max_chars=24000):
    """按实际规范 JSON 字符分包；只投影文字和身份，不携带任意附加字段。"""
    # text 已完整包含标题与摘要；不再重复发送 title/summary，减少同一原文的输入开销。
    fields = ("article_id", "text", "text_hash", "source_group_id", "text_kind")
    return _pack([{key: row[key] for key in fields} for row in records], max_chars)


def validate_proposal(records, proposal):
    """检查完整主归属及有原文锚点的次级关系；返回白名单结构。"""
    catalogue = {row["article_id"]: row for row in records}
    if len(catalogue) != len(records):
        raise ValueError("文章 ID 重复")
    context = _required(proposal.get("analysis_context_id"), "analysis_context_id")
    contexts = proposal.get("analysis_context_ids", [context])
    if not isinstance(contexts, list) or any(not isinstance(c, str) or not c.strip() for c in contexts):
        raise ValueError("analysis_context_ids 必须由宿主填写实际分析上下文列表")
    contexts = sorted(set([context, *contexts]))
    themes = []
    for theme in proposal.get("themes", []):
        themes.append({field: _required(theme.get(field), field) for field in THEME_FIELDS})
    theme_ids = {theme["theme_id"] for theme in themes}
    if len(theme_ids) != len(themes):
        raise ValueError("主题 ID 重复")
    cleaned = {"analysis_context_id": context, "analysis_context_ids": contexts,
               "themes": themes, "assignments": [], "secondary_assignments": []}
    primary, secondary = {}, set()
    for field, role in (("assignments", "primary"), ("secondary_assignments", "secondary")):
        for item in proposal.get(field, []):
            aid = str(item.get("article_id", ""))
            tid = item.get("theme_id")
            if aid not in catalogue or (tid is not None and tid not in theme_ids):
                raise ValueError("归属包含未知文章或主题")
            reason = _required(item.get("reason"), "reason")
            anchor = item.get("anchor") or ""
            if tid is not None:
                anchor = _required(anchor, "anchor")
                if anchor not in catalogue[aid]["text"]:
                    raise ValueError(f"锚点不是原文连续子串：{aid}")
            if role == "primary":
                if aid in primary:
                    raise ValueError(f"主归属重复：{aid}")
                primary[aid] = tid
            elif tid is None or (aid, tid) in secondary or primary.get(aid) == tid:
                raise ValueError("次级关系为空、重复或复制主归属")
            else:
                secondary.add((aid, tid))
            cleaned[field].append({"article_id": aid, "theme_id": tid,
                                   "anchor": anchor, "reason": reason})
    if set(primary) != set(catalogue):
        raise ValueError("每篇文章必须有且只有一个主归属去向（允许 null）")
    return cleaned


def _relationships(records, proposal):
    catalogue = {row["article_id"]: row for row in records}
    themes = {theme["theme_id"]: theme for theme in proposal["themes"]}
    packets = []
    for field, role in (("assignments", "primary"), ("secondary_assignments", "secondary")):
        for assignment in proposal[field]:
            if assignment["theme_id"] is None:
                continue
            aid, tid = assignment["article_id"], assignment["theme_id"]
            packet = {"article_id": aid, "theme_id": tid, "role": role,
                      "text": catalogue[aid]["text"], "theme": themes[tid], "assignment": assignment}
            # 每个关系单独绑定定义、原文、理由及分析上下文；局部修订只使受影响复核失效。
            packet["binding_hash"] = _digest({**packet, "analysis_context_ids": proposal["analysis_context_ids"]})
            packets.append(packet)
    return packets


def review_packets(records, proposal, max_chars=24000):
    """生成供全新上下文逐关系审阅的文字包，主次关系均需覆盖。"""
    proposal = validate_proposal(records, proposal)
    return _pack(_relationships(records, proposal), max_chars)


def compile_result(records, proposal, reviews, min_source_groups=3):
    """仅独立复核 supported 的去重来源进入正式趋势；弱线索完整留池。"""
    if isinstance(min_source_groups, bool) or not isinstance(min_source_groups, int) or min_source_groups < 2:
        raise ValueError("多篇支持阈值必须为至少 2 的整数")
    proposal = validate_proposal(records, proposal)
    packets = _relationships(records, proposal)
    key_of = lambda item: (item["article_id"], item["theme_id"], item["role"])
    expected = {key_of(packet): packet for packet in packets}
    catalogue = {row["article_id"]: row for row in records}
    review_rows = reviews.get("reviews", []) if isinstance(reviews, dict) else reviews
    checked = {}
    for review in review_rows:
        key = (str(review.get("article_id", "")), review.get("theme_id"), review.get("role"))
        if key not in expected or key in checked:
            raise ValueError("复核存在未知、重复或角色不匹配的关系")
        packet = expected[key]
        if review.get("binding_hash") != packet["binding_hash"]:
            raise ValueError("复核绑定失效：文章、主题定义、关系或分析上下文已改变")
        review_context = _required(review.get("review_context_id"), "review_context_id")
        if review_context in proposal["analysis_context_ids"]:
            raise ValueError("复核必须使用不同于所有分析阶段的真实独立上下文")
        status = review.get("status")
        if status not in {"supported", "uncertain", "unsupported"}:
            raise ValueError("复核状态非法")
        anchor = _required(review.get("anchor"), "review.anchor")
        if anchor not in packet["text"]:
            raise ValueError("复核引文不是原文连续子串")
        checked[key] = {"article_id": key[0], "theme_id": key[1], "role": key[2],
                        "status": status, "anchor": anchor,
                        "reason": _required(review.get("reason"), "review.reason"),
                        "binding_hash": packet["binding_hash"], "review_context_id": review_context}
    if set(checked) != set(expected):
        raise ValueError("复核未覆盖全部主归属及次级关系")
    by_theme = defaultdict(list)
    for review in checked.values():
        by_theme[review["theme_id"]].append(review)
    ranked, candidates = [], []
    for theme in proposal["themes"]:
        relationships = by_theme[theme["theme_id"]]
        supported = [item for item in relationships if item["status"] == "supported"]
        articles = {item["article_id"] for item in supported}
        groups = {catalogue[aid]["source_group_id"] for aid in articles}
        primary = [item for item in supported if item["role"] == "primary"]
        primary_groups = {catalogue[item["article_id"]]["source_group_id"] for item in primary}
        result = {**theme, "source_group_count": len(groups), "article_count": len(articles),
                  "primary_source_group_count": len(primary_groups),
                  "primary_article_count": len(primary), "members": primary,
                  "secondary_members": [item for item in supported if item["role"] == "secondary"],
                  "reviews": relationships, "eligible": len(groups) >= min_source_groups}
        if result["eligible"]:
            ranked.append(result)
        else:
            result["pool_reason"] = f"已复核去重来源组 {len(groups)}，低于门槛 {min_source_groups}"
            candidates.append(result)
    priority = lambda item: (-item["source_group_count"], -item["primary_source_group_count"],
                            -item["article_count"], item["theme_id"])
    ranked.sort(key=priority)
    candidates.sort(key=priority)
    for rank, theme in enumerate(ranked, 1):
        theme["priority_rank"] = rank
    supported_articles = {r["article_id"] for r in checked.values() if r["status"] == "supported"}
    return {"version": VERSION, "min_source_groups": min_source_groups, "themes": ranked,
            "ranking": [{key: theme[key] for key in ("theme_id", "title", "priority_rank", "source_group_count",
                         "primary_source_group_count", "article_count")} for theme in ranked],
            "candidate_pool": candidates, "records": records, "proposal": proposal,
            "coverage": {"article_count": len(records), "reviewed_relation_count": len(checked),
                         "supported_article_count": len(supported_articles),
                         "unassigned": [a for a in proposal["assignments"] if a["theme_id"] is None],
                         "uncertain": [r for r in checked.values() if r["status"] == "uncertain"],
                         "unsupported": [r for r in checked.values() if r["status"] == "unsupported"],
                         "without_supported_relation": sorted(set(catalogue) - supported_articles)}}


def main():
    """离线 CLI：prepare 只整理文字，compile 只验证已有提案与真实复核。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--max-chars", type=int, default=24000)
    compile_parser = sub.add_parser("compile")
    for name in ("corpus", "proposal", "reviews", "out"):
        compile_parser.add_argument("--" + name, type=Path, required=True)
    compile_parser.add_argument("--min-source-groups", type=int, default=3)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    if args.command == "prepare":
        rows = read(args.input)
        records = normalize_records(rows.get("records", []) if isinstance(rows, dict) else rows)
        outputs = {"corpus.json": records, "packets.json": pack_records(records, args.max_chars)}
    else:
        outputs = {"result.json": compile_result(read(args.corpus), read(args.proposal), read(args.reviews), args.min_source_groups)}
    args.out.mkdir(parents=True, exist_ok=True)
    for name, value in outputs.items():
        (args.out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

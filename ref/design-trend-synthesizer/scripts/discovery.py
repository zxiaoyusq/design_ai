"""有覆盖清单的用户主题归纳、代表证据配对和候选提前核对。"""

from collections import Counter

from core import USER_KINDS, batches, digest, encode, make_job, public_evidence, write
from contexts import attach_sources, evidence_batches


def theme_jobs(run, evidence, settings, records):
    trend_dimensions = {d for e in evidence.values() if e["kind"] == "trend" for d in e["dimensions"]}
    eligible = [public_evidence(e) for e in evidence.values()
                if e["kind"] != "trend" and trend_dimensions.intersection(e["dimensions"])]
    eligible.sort(key=lambda e: (e["dimensions"], e.get("user_id") or "", e["record_id"], e["id"]))
    # 提取不再生成 context；主题必须能回看完整问答，不能把“喜欢”脱离原问题归类。
    return [make_job(run, "theme", index, pack, {"max_themes": 8})
            for index, pack in enumerate(evidence_batches(eligible, {}, records, 32, settings["batch_chars"]))]


def materialize_themes(results):
    themes = []
    for job, response in results:
        for index, item in enumerate(response["themes"]):
            value = {**item, "origin_job": job["id"], "origin_index": index}
            themes.append({"id": "t-" + digest(value)[:24], **value})
    return themes


def representatives(theme, evidence):
    """为不同立场优先留位，再补不同用户；人数与最终反证仍从完整证据回算。"""
    pool = sorted((evidence[eid] for eid in theme["evidence_ids"]
                   if evidence[eid]["kind"] in USER_KINDS), key=lambda e: e["id"])
    selected = []
    for stance in ("counter", "conditional", "support", "unclear"):
        hit = next((e for e in pool if e["stance"] == stance), None)
        if hit is not None:
            selected.append(hit)
    for item in pool:
        if len(selected) >= 4:
            break
        if item["id"] not in {e["id"] for e in selected} and item.get("user_id") not in {e.get("user_id") for e in selected}:
            selected.append(item)
    return selected[:4]


def propose_jobs(run, evidence, themes, records, settings):
    """每个主题只生成与其维度相交的趋势组合，保存所有未作为代表送入候选的证据。"""
    trend_items = [e for e in evidence.values() if e["kind"] == "trend"]
    groups = {}
    representative_ids, matched_ids, theme_index = set(), set(), []
    for theme in themes:
        reps = representatives(theme, evidence)
        # 召回使用成员已有维度的并集，主题摘要少写一个维度不能让多维原观察失去配对机会。
        retrieval_dimensions = {d for eid in theme["evidence_ids"] for d in evidence[eid]["dimensions"]}
        related = sorted((e for e in trend_items if set(e["dimensions"]).intersection(retrieval_dimensions)), key=lambda e: e["id"])
        summary = {k: theme[k] for k in ("id", "title", "summary", "dimensions")}
        summary["retrieval_dimensions"] = sorted(retrieval_dimensions)
        summary["representative_evidence_ids"] = [e["id"] for e in reps]
        theme_index.append({**summary, "all_evidence_ids": theme["evidence_ids"]})
        if not reps or not related:
            continue
        matched_ids.update(theme["evidence_ids"])
        representative_ids.update(e["id"] for e in reps)
        # 先按相同趋势集合合并主题，避免每个原始用户小批重复产生相同趋势组合。
        key = tuple(e["id"] for e in related)
        groups.setdefault(key, []).append((summary, reps))
    jobs = []
    for key, members in sorted(groups.items()):
        related = [public_evidence(evidence[eid]) for eid in key]
        # 趋势也只按完整来源预算分小批；共同原则的语义成立由 screen 核对。
        trend_packs = batches(related, 8, settings["batch_chars"] // 3)
        for trend_pack in trend_packs:
            current = []

            def payload(pack):
                user_evidence = {e["id"]: public_evidence(e) for _, reps in pack for e in reps}
                return attach_sources({"evidence": trend_pack + list(user_evidence.values()),
                                       "user_themes": [summary for summary, _ in pack]}, records)

            for member in members:
                trial = payload(current + [member])
                if current and (len(current) >= 8 or len(encode(trial)) > settings["batch_chars"]):
                    jobs.append(make_job(run, "propose", len(jobs), payload(current), {"max_candidates": 4}))
                    current = []
                    trial = payload([member])
                if len(encode(trial)) > settings["batch_chars"]:
                    raise ValueError("单个主题的代表证据与原文超过字符预算；增大 --batch-chars，不能删掉反对立场")
                current.append(member)
            if current:
                jobs.append(make_job(run, "propose", len(jobs), payload(current), {"max_candidates": 4}))
    dimension_counts = {}
    for side in ("trend", "user"):
        dimension_counts[side] = dict(Counter(d for e in evidence.values()
            if (e["kind"] == "trend") == (side == "trend") for d in e["dimensions"]))
    write(run / "retrieval_report.json", {
        "dimension_counts": dimension_counts, "theme_count": len(themes), "propose_job_count": len(jobs),
        "theme_index": theme_index, "representative_evidence_ids": sorted(representative_ids),
        "theme_member_not_representative_ids": sorted(matched_ids - representative_ids),
        "unpaired_evidence_ids": sorted(eid for eid, e in evidence.items() if e["kind"] != "trend" and eid not in matched_ids),
        "recall_boundary": "主题完整覆盖可配对维度的用户观察；候选仅用有来源的主题摘要及分立场代表。完整反证仍覆盖候选全部维度，未成为代表不表示无价值。"})
    return jobs


def screen_jobs(run, candidates, evidence, records, settings):
    def payload(pack):
        ids = sorted({eid for c in pack for eid in c["evidence_ids"]})
        return attach_sources({"candidates": pack, "evidence": [public_evidence(evidence[eid]) for eid in ids]}, records)

    jobs, current = [], []
    for candidate in candidates:
        trial = payload(current + [candidate])
        if current and (len(current) >= 8 or len(encode(trial)) > settings["batch_chars"]):
            jobs.append(make_job(run, "screen", len(jobs), payload(current)))
            current = []
            trial = payload([candidate])
        if len(encode(trial)) > settings["batch_chars"]:
            raise ValueError("单候选及完整核对原文超过字符预算；增大 --batch-chars，不省略支持依据")
        current.append(candidate)
    if current:
        jobs.append(make_job(run, "screen", len(jobs), payload(current)))
    return jobs

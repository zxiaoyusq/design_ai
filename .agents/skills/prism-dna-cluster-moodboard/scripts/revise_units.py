"""按真实板审的问题定点复核原图单元，保存可回查补丁，不覆盖旧观察。"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from model_runtime import execute_structured, ref, write_new
from observe_sample import (SYSTEM, ID_FIELDS, CMF_FIELDS, SUBJECT_FIELDS, DISPLAY_FIELDS, obj, unit_schema, decode_unit,
                            observed_version, prepare_payload, compact_model_payload, update_derived_coverage)
from design_emotion import primary_subject_binding, selected_subject_groups


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_schema() -> dict:
    text = {"type": "string"}
    alternatives = [unit_schema("ID", ID_FIELDS, wire=False), unit_schema("CMF", CMF_FIELDS, wire=False)]
    for alternative in alternatives:
        # 事实修订使原组合解释失效；本调用不夹带未经对象分组核对的新情绪。
        alternative["properties"]["design_emotion"] = {"type": "null"}
    return obj({"revisions": {"type": "array", "items": obj({
        "unit_id": text, "image_id": text, "change_reason": text,
        "observation": {"anyOf": alternatives}})}})


def validate_revision_subject(old: dict, new: dict) -> None:
    """定点修订不换对象；身份名不变、原新定位有交集，具体校框仍须真实审阅。"""
    if "primary_subject" not in old:
        # 原协议没有对象声明时只能经真实原图重观察补全，不从历史局部猜对象身份。
        return
    bindings = []
    for item in (old, new):
        # 这里仅复用身份与坐标结构核验，不赋予该单元主物品资格或usable判定。
        binding = primary_subject_binding([{"usable": True, "target_role": "primary_object",
                                            "primary_subject": item.get("primary_subject")}])
        bindings.append(binding)
    prior, revised = bindings
    if prior["identity"] != revised["identity"]:
        raise ValueError("定点修订不能更换所选对象身份；另一个对象须建立新观察单元")
    left, right = prior["bbox"], revised["bbox"]
    overlap_width = min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0])
    overlap_height = min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1])
    if overlap_width <= 0 or overlap_height <= 0:
        raise ValueError("定点修订对象框不能跳到无交集的另一位置；另一个对象须建立新观察单元")


def apply_revisions(base: dict, revisions: dict) -> dict:
    """补丁只替换完全匹配的原单元；后续全集进度可变化，目标原事实必须仍一致。"""
    result = deepcopy(base)
    current = {u["unit_id"]: u for u in base["units"]}
    replacements, affected_images = {}, set()
    for row in revisions["revisions"]:
        old, new = row["previous"], row["revised"]
        if current.get(old["unit_id"]) != old:
            raise ValueError(f"补丁原观察与当前单元不一致: {old['unit_id']}")
        if new["unit_id"] != old["unit_id"] or new["image_sha256"] != old["image_sha256"]:
            raise ValueError("定点复核不能换图或换单元身份")
        validate_revision_subject(old, new)
        # 新观察字段必须与它实际采用的协议一致，不能继承待修订单元的旧版本标签。
        if new.get("feature_definition_version", observed_version(new)) != observed_version(new):
            raise ValueError("修订字段与feature_definition_version不一致")
        if (new.get("design_emotion") is not None
                and (new.get("design_emotion") != old.get("design_emotion")
                     or new.get("design_emotion_provenance") != old.get("design_emotion_provenance"))):
            raise ValueError("单元修订不能夹带新图级情绪，请在修订后使用情绪补查流程")
        replacements[old["unit_id"]] = deepcopy(new)
        affected_images.add(old["image_id"])
    invalidated_emotions = []
    for row in result["images"]:
        row["units"] = [replacements.get(u["unit_id"], u) for u in row.get("units", [])]
        if row["image_id"] in affected_images:
            previous_image = next(image for image in base["images"] if image["image_id"] == row["image_id"])
            if previous_image.get("design_emotion") is not None or any(u.get("design_emotion") is not None for u in previous_image.get("units", [])):
                # v3只作废受修订对象的共享解释，不能牵连同图另一个同级对象。
                changed_ids = {revision["previous"]["unit_id"] for revision in revisions["revisions"]
                               if revision["previous"]["image_id"] == row["image_id"]}
                affected_ids = set(changed_ids)
                # 和观察/补查共用对象分组及坐标尾差，不用dict精确相等漏掉同对象兄弟单元。
                for image_units in (previous_image.get("units", []), row["units"]):
                    for group in selected_subject_groups(image_units):
                        if changed_ids.intersection(group["unit_ids"]):
                            affected_ids.update(group["unit_ids"])
                affected_units = [unit for unit in row["units"] if previous_image.get("design_emotion") is not None
                                  or unit["unit_id"] in affected_ids]
                invalidated_emotions.append({"image_id": row["image_id"],
                    "previous_image_emotion": deepcopy(previous_image.get("design_emotion")),
                    "previous_image_provenance": deepcopy(previous_image.get("design_emotion_provenance")),
                    "previous_unit_emotions": [{"unit_id": u["unit_id"], "design_emotion": deepcopy(u.get("design_emotion")),
                                                "design_emotion_provenance": deepcopy(u.get("design_emotion_provenance"))}
                                               for u in previous_image.get("units", [])
                                               if u["unit_id"] in {member["unit_id"] for member in affected_units}],
                    "reason": "单元事实修订后只补受影响对象整体组合，同图其他对象情绪保留"})
                targets = ([row] if previous_image.get("design_emotion") is not None else []) + affected_units
                for target in targets:
                    target.update(design_emotion=None, design_emotion_provenance=None,
                                  design_emotion_status="needs_recheck")
    result_by_unit = {u["unit_id"]: u for row in result["images"] for u in row.get("units", [])}
    result["units"] = [deepcopy(result_by_unit.get(u["unit_id"], u)) for u in result["units"]]
    result.setdefault("unit_revision_history", []).append({
        "unit_ids": sorted(replacements), "model_answer_ref": revisions["model_answer_ref"],
        "independent_review_ref": revisions["independent_review_ref"],
        "invalidated_design_emotions": invalidated_emotions, "human_approved": False})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--unit-ids", nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--patch", type=Path, help="已有补丁的纯离线应用，不新增模型调用")
    args = parser.parse_args()
    base = read(args.observations)
    if args.patch:
        result = apply_revisions(base, read(args.patch))
        result["revision_application_inputs"] = {"observations": ref(args.observations), "patch": ref(args.patch)}
        write_new(args.out, result)
        print(json.dumps({"model_calls": 0, "output": str(args.out)}, ensure_ascii=False))
        return
    if not args.reviews or not args.unit_ids or not 1 <= len(args.unit_ids) <= 10:
        parser.error("模型定点复核需要 --reviews 与 1–10 个 --unit-ids")
    if len(set(args.unit_ids)) != len(args.unit_ids):
        raise ValueError("重复单元")
    args.out.mkdir(parents=True, exist_ok=False)
    units = {u["unit_id"]: u for u in base["units"]}
    images = {x["image_id"]: x for x in base["images"]}
    requested = [units[uid] for uid in args.unit_ids]
    review_items = {m["unit_id"]: m for b in read(args.reviews)["reviews"] for m in b["members"]}
    if not set(args.unit_ids) <= set(review_items):
        raise ValueError("每个目标都必须有当前真实板审问题出处")
    image_ids = list(dict.fromkeys(u["image_id"] for u in requested))
    context, attachments = prepare_payload([images[i] for i in image_ids])
    write_new(args.out / "r5-context.json", context)
    source_units = []
    for u in requested:
        item = review_items[u["unit_id"]]
        if item["image_id"] != u["image_id"]:
            raise ValueError("板审对象身份不符")
        source_units.append({"unit_id": u["unit_id"], "image_id": u["image_id"],
                             "current_observation": {k: v for k, v in u.items() if k in {
                                 "branch", "scope", "bbox", "whole_object_visible", "usable", "features",
                                 "evidence", "limitations", "feature_definition_version"} | SUBJECT_FIELDS | DISPLAY_FIELDS},
                             "independent_review_issue": item})
    payload = {**compact_model_payload(context), "target_units": source_units,
               "prompt_version": "prism-dna-targeted-revision-v3", "review_ref": ref(args.reviews),
               "base_observations_ref": ref(args.observations), "script_ref": ref(Path(__file__)),
               "r5_context_ref": ref(args.out / "r5-context.json")}
    # 保留原字段锚点，去掉批处理的短键传输约定；本阶段仍只复核规定的同一目标。
    system = SYSTEM.split("\n输出压缩规则：")[0] + """
本次是有依据的定点复核，只输出target_units逐项修订，不重提同图其他对象。unit_id/image_id必须原样保留。
实际查看本次原图，先判断板审问题是否成立，再重新核对现有字段及范围；板审意见是待核问题，不是强制答案。
所有已有字段仍按相同锚点输出完整分块features对象。保留有证据的宏观纹理，不能因为微观组织不可见就改成none；仅未知的字段填null。
完整复核target_role、primary_subject、evidence_bbox、display_bbox、display_scope、crop_reason、whole_appearance与design_quality；旧协议缺新字段时须实际观察，不从裁框大小猜资格。所选对象可主物品或明确同级物品，但定点修订不得悄悄换成另一件；原本只是背景碎片仍不可用。ID和CMF均可代表性局部，须明确观察限制，整物不可知事实填null。
本次仅修订事实及取景，design_emotion必须填null；修订后对受影响对象另作有界组合情绪补查，不能沿用旧解释，也不能把当前调用当成完整情绪评审。
不要为了获得同簇或通过判定而修改值，不引入品类和风格标签。实际裁片范围不合标准时usable=false并说明；仅当新ROI仍表达同一目标且有足够可读证据时可修订ROI。
只返回revisions数组，每个指定目标恰好一次，包含原身份、完整observation和具体change_reason。旧事实引用只能来自本次给出的R5子集。
"""
    folder = args.out / "call"
    answer = execute_structured(folder, system=system, payload=payload, images=attachments, schema=make_schema())
    rows = answer["revisions"]
    if len(rows) != len(requested) or {r["unit_id"] for r in rows} != set(args.unit_ids):
        raise ValueError("模型没有完整覆盖指定单元")
    facts_by_image = {r["image_id"]: r["r5"] for r in context["images"]}
    revisions = []
    for index, row in enumerate(rows):
        old = units[row["unit_id"]]
        observed = decode_unit(row["observation"])
        if row["image_id"] != old["image_id"] or observed["branch"] != old["branch"]:
            raise ValueError("目标身份或分支改变")
        validate_revision_subject(old, observed)
        x, y, w, h = observed["bbox"]
        if w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
            raise ValueError("复核ROI不合法")
        r5 = facts_by_image[row["image_id"]]
        facts = {f["fact_id"]: f for f in r5["facts"]}
        if not set(observed["reused_fact_ids"]) <= set(facts):
            raise ValueError("复核引用了未提供的旧R5事实")
        new = {**old, **observed,
               "feature_definition_version": observed_version(observed),
               "reused_fact_refs": [{"source_ref": r5["source_ref"], "pointer": facts[f]["pointer"], "fact_id": f}
                                    for f in observed["reused_fact_ids"]],
               "observation_ref": ref(folder / "answer.json"),
               "observation_pointer": f"/revisions/{index}/observation", "receipt_ref": ref(folder / "receipt.json"),
               "previous_observation_ref": old["observation_ref"], "previous_observation_pointer": old["observation_pointer"],
               "revision_reason": row["change_reason"], "model_requested": "gpt-6.1-sol", "reasoning_effort_requested": "high"}
        if old.get("design_emotion") is not None:
            new.update(design_emotion=None, design_emotion_provenance=None, design_emotion_status="needs_recheck")
        new = update_derived_coverage({"units": [new]})["units"][0]
        revisions.append({"previous": old, "revised": new, "change_reason": row["change_reason"]})
    result = {"schema_version": "prism.unit-revisions.v1", "base_observations_ref": ref(args.observations),
              "independent_review_ref": ref(args.reviews), "model_answer_ref": ref(folder / "answer.json"),
              "receipt_ref": ref(folder / "receipt.json"), "revisions": revisions, "human_approved": False}
    write_new(args.out / "unit-revisions.json", result)
    print(json.dumps({"revised_units": len(revisions), "output": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

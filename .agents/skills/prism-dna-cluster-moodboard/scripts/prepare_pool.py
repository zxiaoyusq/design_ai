"""冻结旧选向覆盖的全部原图，并进行与语义、DNA可用性无关的稳定随机抽样。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[4]
H01 = ROOT / "data/result/semantic_handshake/sol61_native_v2_20261006"
INVENTORY = ROOT / "data/result/visual_workflow/h01_all13_20261005_expanded/inventory.json"
NEW_DNA = ROOT / "data/result/visual_completion/sol61_high_20261007/new-dna"
DEFAULT_OUT = ROOT / "data/result/dna_cluster_moodboard/sample500_20261009"


def read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def absolute_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return str((path if path.is_absolute() else ROOT / path).resolve())


def sample_key(image_sha: str, seed: str) -> str:
    """对唯一原图做确定性的散列随机排列；不读取类别、方向、DNA或品质。"""
    return hashlib.sha256(f"{seed}:{image_sha}".encode("utf-8")).hexdigest()


def dna_index(inventory_path: Path, new_dna_dir: Path) -> tuple[dict, list[dict]]:
    """保留历史多版本，仅以已有冻结选择及后来有出处的补提结果指定首选版本。"""
    indexed: dict[str, dict] = {}
    new_inputs: list[dict] = []
    for row in read(inventory_path):
        refs = []
        selected = row.get("selected_dna_ref")
        for variant in row.get("dna_variants", []):
            source_ref = variant["result_ref"]
            refs.append({
                "path": absolute_path(source_ref["path"]),
                "sha256": source_ref["sha256"],
                "model": variant.get("model_id"),
                "status": variant.get("stored_status") or (
                    "completed" if variant.get("stage_complete") else "partial"
                ),
                "status_basis": "archived_variant_stored_status_or_stage_complete",
                "kind": "archived_r5",
                "reasoning_effort": variant.get("reasoning_effort"),
                "schema_version": variant.get("schema_version"),
                "prompt_sha256": variant.get("prompt_sha256"),
                "pending_count": variant.get("pending_count"),
                "invalid_count": variant.get("invalid_count"),
                "local_feature_count": variant.get("local_feature_count"),
                "selected": source_ref == selected,
                "original_variant": variant,
            })
        # 若未来清单只给首选引用而未重复列进多版本，仍保留明确的来源记录。
        if selected and not any(ref["selected"] for ref in refs):
            refs.append({
                **selected, "path": absolute_path(selected["path"]),
                "model": None, "status": row["dna_readiness"],
                "status_basis": "archived_image_readiness",
                "kind": "archived_r5", "selected": True,
            })
        indexed[row["image_sha256"]] = {
            "refs": refs,
            "readiness": row["dna_readiness"],
            "eligible_for_dna_recall": row["eligible_for_dna_recall"],
            "new_result_count": 0,
            "batch_entries": row.get("batch_entries", []),
        }

    # 补提索引曾早于20664结果落盘；扫描实际result+record，不能只依赖旧成功计数。
    results = [(path, read(path)) for path in sorted(new_dna_dir.glob("*/result.json"))]
    results.sort(key=lambda item: (item[1].get("executed_at", ""), str(item[0])))
    for path, data in results:
        record_path = path.with_name("record.json")
        record = read(record_path)
        image_sha = data["image_sha256"]
        if record["image_sha256"] != image_sha or record["asset"]["sha256"] != image_sha:
            raise ValueError(f"补提结果与原图绑定不一致：{path}")
        result_ref, record_ref = file_ref(path), file_ref(record_path)
        new_inputs.append({"result_ref": result_ref, "record_ref": record_ref})
        row = indexed.setdefault(image_sha, {
            "refs": [], "readiness": "not_in_inventory",
            "eligible_for_dna_recall": False, "new_result_count": 0,
            "batch_entries": [],
        })
        for old in row["refs"]:
            old["selected"] = False
        row["refs"].append({
            **result_ref,
            "model": data.get("model"), "status": data.get("status"),
            "status_basis": "portable_result.status", "kind": "portable_r5",
            "reasoning_effort": data.get("reasoning_effort"),
            "schema_version": data.get("schema_version"),
            "algorithm_version": data.get("algorithm_version"),
            "pending_count": data.get("pending_count"),
            "invalid_count": len(data.get("invalid", [])),
            "local_feature_count": len(data.get("local_features", [])),
            "executed_at": data.get("executed_at"), "record_ref": record_ref,
            "selected": True,
        })
        row["new_result_count"] += 1
        row["eligible_for_dna_recall"] = True
    return indexed, new_inputs


def build_pool(articles: list[dict], selected_ids: set[str], dna: dict) -> tuple[list, list, int]:
    """仅用旧方向ID限定文章范围；整篇所有关联原图均登记，包括多角度和失败。"""
    by_sha: dict[str, dict] = {}
    unresolved = []
    article_count = 0
    image_id_shas: dict[str, str] = {}
    for article in articles:
        memberships = article["direction_membership"]
        direction_ids = sorted(selected_ids & {m["direction_id"] for m in memberships})
        if not direction_ids:
            continue
        article_count += 1
        metadata = article["metadata"]
        source = {
            "article_id": article["original_id"], "source_id": article["source_id"],
            "title": article["title"], "article_url": metadata.get("detail_url"),
            "publisher": article.get("publisher_group"),
            "category": metadata.get("primary_category"),
            "subcategory": metadata.get("subcategory"), "metadata": metadata,
            "direction_ids": direction_ids,
            "all_direction_membership": memberships,
            "source_group_id": article.get("source_group_id"),
            "claim_origin_id": article.get("claim_origin_id"),
            "project_id": None, "project_identity_state": "not_registered_by_this_stage",
        }
        for image in article["images"]:
            original_sha = image.get("sha256")
            alias = {
                "image_id": image["image_id"], "article_id": article["original_id"],
                "source_id": article["source_id"], "direction_ids": direction_ids,
                "local_path": absolute_path(image.get("absolute_local_path") or image.get("local_path")),
                "image_url": image.get("url"), "article_url": metadata.get("detail_url"),
                "status": image.get("status"), "image_metadata": image,
            }
            if not original_sha or not re.fullmatch(r"[0-9a-f]{64}", original_sha):
                unresolved.append({
                    "reason": "missing_or_invalid_original_sha256", "alias": alias,
                    "source": source,
                })
                continue
            previous = image_id_shas.setdefault(image["image_id"], original_sha)
            if previous != original_sha:
                raise ValueError(f"同一image_id指向不同原图SHA：{image['image_id']}")
            row = by_sha.setdefault(original_sha, {"sha256": original_sha, "aliases": [], "sources": []})
            row["aliases"].append(alias)
            if not any(s["article_id"] == source["article_id"] for s in row["sources"]):
                row["sources"].append(source)

    for image_sha, row in by_sha.items():
        row["aliases"].sort(key=lambda a: (a["image_id"], a["article_id"], a["local_path"] or ""))
        row["sources"].sort(key=lambda s: s["article_id"])
        canonical = row["aliases"][0]
        usable_path = next((a["local_path"] for a in row["aliases"] if a["local_path"] and Path(a["local_path"]).is_file()), canonical["local_path"])
        entry = dna.get(image_sha)
        refs = entry["refs"] if entry else []
        selected = next((ref for ref in refs if ref.get("selected")), None)
        row.update({
            "image_id": canonical["image_id"], "local_path": usable_path,
            "image_url": canonical["image_url"],
            "direction_ids": sorted({d for s in row["sources"] for d in s["direction_ids"]}),
            "source_kind": "trend", "dna_refs": refs, "dna_primary_ref": selected,
            "dna_state": "new_R5" if entry and entry["new_result_count"] else entry["readiness"] if entry else "not_in_inventory",
            "dna_processing_status": "available_for_field_audit" if selected else "needs_dna",
            "dna_batch_entries": entry["batch_entries"] if entry else [],
            "image_sha_validation": "not_recomputed_at_pool_stage",
            "visual_quality_status": "not_reviewed_in_this_run",
            "runway_state": "unknown", "runway_classification_basis": None,
        })
    return [by_sha[key] for key in sorted(by_sha)], unresolved, article_count


def verify_sample(images: list[dict]) -> list[dict]:
    """核验已抽出的真实原图及其DNA文件；失败保留在样本内，不靠换图掩盖。"""
    errors = []
    checked_refs: dict[str, str] = {}
    for image in images:
        path = Path(image["local_path"]) if image["local_path"] else None
        actual = sha256(path) if path and path.is_file() else None
        image["image_sha_validation"] = "verified" if actual == image["sha256"] else "failed"
        if actual != image["sha256"]:
            errors.append({"kind": "original_image_sha_mismatch_or_missing", "image_id": image["image_id"], "actual_sha256": actual})
        for dna_ref in image["dna_refs"]:
            refs = [dna_ref] + ([dna_ref["record_ref"]] if dna_ref.get("record_ref") else [])
            for ref in refs:
                ref_path = Path(ref["path"])
                if ref["path"] not in checked_refs:
                    checked_refs[ref["path"]] = sha256(ref_path) if ref_path.is_file() else "missing"
                if checked_refs[ref["path"]] != ref["sha256"]:
                    errors.append({"kind": "dna_file_sha_mismatch_or_missing", "image_id": image["image_id"], "ref": ref})
    return errors


def write_fresh(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def resolve_direction_scope(selection: dict, articles: dict, result: dict | None,
                            result_sha: str | None) -> set[str]:
    """全量高潜必须来自同版显式判定；没有状态映射时拒绝把已选方向冒充全集。"""
    if result is None:
        return {row["direction_id"] for row in selection["selection"]}
    directions = result.get("directions", [])
    if not directions or any("decision" not in row for row in directions):
        raise ValueError("该方向版本没有明确 decision，不能自动映射为 high_potential")
    expected = {row["direction_id"] for row in directions if row["decision"] == "high_potential"}
    if not expected:
        raise ValueError("来源未包含可追溯的 high_potential 方向")
    selected = set(selection.get("selected_direction_ids", []))
    if selected != expected:
        raise ValueError("选择清单必须精确包含全部高潜方向，不允许 Top5／七方向隐式截断")
    if selection.get("result_sha256") != result_sha or articles.get("result_sha256") != result_sha:
        raise ValueError("方向选择／文章关联与实际结果 SHA 不一致")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=Path, default=H01 / "related-trend-articles.json")
    parser.add_argument("--selection", type=Path, default=H01 / "h01-run/selection.json")
    parser.add_argument("--high-potential-result", type=Path,
                        help="显式 decision=high_potential 的权威结果；验证全量选择及来源SHA")
    parser.add_argument("--scope-only", action="store_true", help="仅离线冻结范围，不抽样、不调用模型")
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--new-dna-dir", type=Path, default=NEW_DNA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--size", type=int, default=500)
    parser.add_argument("--seed", default="20261009")
    args = parser.parse_args()
    if args.size <= 0:
        raise ValueError("样本数必须为正数")
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("pool.json", "sample.json", "pool-preparation-audit.json"):
        if (args.out / name).exists():
            raise FileExistsError(f"拒绝覆盖既有冻结产物：{args.out / name}")
    article_data = read(args.articles)
    result = read(args.high_potential_result) if args.high_potential_result else None
    selected_ids = resolve_direction_scope(read(args.selection), article_data, result,
                                          sha256(args.high_potential_result) if result is not None else None)
    dna, new_inputs = dna_index(args.inventory, args.new_dna_dir)
    images, unresolved, article_count = build_pool(article_data["articles"], selected_ids, dna)
    if not args.scope_only and len(images) < args.size:
        raise ValueError(f"唯一原图只有{len(images)}张，不足抽取{args.size}张")
    # 先完成全集再抽样；没有R5、曾失败、秀场及旧品质未过的图片均有同样机会。
    ordered = sorted(images, key=lambda image: (sample_key(image["sha256"], args.seed), image["sha256"]))
    sampled = [] if args.scope_only else json.loads(json.dumps(ordered[:args.size], ensure_ascii=False))
    for rank, row in enumerate(sampled, 1):
        row["sampling_rank"] = rank
        row["sampling_key"] = sample_key(row["sha256"], args.seed)
    errors = verify_sample(sampled)
    created_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    sources = {
        "related_articles": file_ref(args.articles), "scope_selection": file_ref(args.selection),
        "archived_dna_inventory": file_ref(args.inventory), "supplemental_dna_inputs": new_inputs,
        "script": file_ref(Path(__file__)),
    }
    if args.high_potential_result:
        sources["high_potential_result"] = file_ref(args.high_potential_result)
    scope = {
        "mode": "all_explicit_high_potential_directions" if result is not None else "legacy_selected_direction_ids_as_image_scope_only",
        "direction_ids": sorted(selected_ids), "top5_selection_performed": False,
        "semantic_titles_or_rules_used_for_sampling": False,
        "source_kind": "trend", "research_images_added": False,
        "article_count": article_count,
        "associated_image_references": sum(len(row["aliases"]) for row in images) + len(unresolved),
        "unique_original_images": len(images), "unresolved_image_references": len(unresolved),
    }
    pool = {
        "schema_version": "prism.dna_cluster_pool.v1", "created_at": created_at,
        "inputs": sources, "scope": scope, "images": images,
        "unresolved_image_references": unresolved,
        "dna_state_counts": dict(Counter(row["dna_state"] for row in images)),
        "model_calls": 0, "quality_or_field_accuracy_established": False,
    }
    write_fresh(args.out / "pool.json", pool)
    if args.scope_only:
        audit = {"pool_ref": file_ref(args.out / "pool.json"), "scope": scope,
                 "dna_state_counts": pool["dna_state_counts"], "model_calls": 0,
                 "original_bytes_recomputed": False, "sample_created": False,
                 "historical_quality_filter_applied": False,
                 "quality_note": "未覆盖人工FAIL/模型PASS历史冲突；范围不等于人审通过。"}
        write_fresh(args.out / "pool-preparation-audit.json", audit)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return
    sampling = {
        "method": "sha256_seeded_uniform_hash_order_without_replacement",
        "key_format": "UTF8(seed + ':' + original_image_sha256)",
        "seed": args.seed, "sample_size": args.size, "population_size": len(images),
        "stratification": None, "filter_by_dna_availability": False,
        "filter_by_semantic_direction_or_style": False,
        "selection_rule": "ascending SHA256 key, original SHA256 tie-break, first N",
    }
    sample = {
        "schema_version": "prism.dna_cluster_sample.v1", "created_at": created_at,
        "pool_ref": file_ref(args.out / "pool.json"), "scope": scope, "sampling": sampling,
        "images": sampled,
        "dna_state_counts": dict(Counter(row["dna_state"] for row in sampled)),
        "image_sha_verification_count": sum(row["image_sha_validation"] == "verified" for row in sampled),
        "verification_errors": errors, "model_calls": 0,
        "quality_or_field_accuracy_established": False,
    }
    write_fresh(args.out / "sample.json", sample)
    audit = {
        "schema_version": "prism.dna_cluster_pool_preparation_audit.v1",
        "created_at": created_at, "scope": scope, "sampling": sampling,
        "outputs": {"pool": file_ref(args.out / "pool.json"), "sample": file_ref(args.out / "sample.json")},
        "pool_dna_state_counts": pool["dna_state_counts"],
        "sample_dna_state_counts": sample["dna_state_counts"],
        "image_sha_verification_count": sample["image_sha_verification_count"],
        "status": "passed" if not errors else "failed", "verification_errors": errors,
        "model_calls": 0,
        "coverage_note": "DNA引用存在仅代表可做字段审计；completed或partial都不等于视觉准确、所有字段已知或已获成板资格。",
        "scope_note": "全部已关联原图都进入全集；缺SHA的失败引用完整单列。原始文章、方向、标题和URL仅用于追溯，不进入DNA距离。",
    }
    write_fresh(args.out / "pool-preparation-audit.json", audit)
    print(json.dumps({k: v for k, v in audit.items() if k not in {"outputs", "coverage_note", "scope_note"}}, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit("样本完整性核验失败；证据已保留，不自动换图或继续模型调用。")


if __name__ == "__main__":
    main()

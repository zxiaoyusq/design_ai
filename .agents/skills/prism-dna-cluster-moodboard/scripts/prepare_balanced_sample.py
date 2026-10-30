"""按原文尽量均衡抽取唯一原图，冻结适用旧观察；不读审美分数、不调用模型。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics


VERSION = "prism.article_balanced_sample.v1"


def read(path: Path):
    return json.loads(path.read_bytes())


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ref(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def write_new(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def key(seed: str, kind: str, identity: str) -> str:
    return hashlib.sha256(f"{seed}:{kind}:{identity}".encode()).hexdigest()


def articles(row: dict) -> list[str]:
    values = {str(source["article_id"]) for source in [*row.get("sources", []), *row.get("aliases", [])]
              if source.get("article_id") is not None}
    if not values:
        raise ValueError(f"原图缺少原文身份，不能猜配额：{row['sha256']}")
    return sorted(values)


def balanced_sample(images: list[dict], size: int, seed: str) -> tuple[list[dict], dict]:
    """先唯一归属，再随机水位轮转；抽样全过程不看 DNA、图片类别或品质。"""
    by_sha = {row["sha256"]: row for row in images}
    if len(by_sha) != len(images):
        raise ValueError("pool 必须已按原图 SHA 去重")
    if not 1 <= size <= len(images):
        raise ValueError("sample size 超出唯一原图范围")
    memberships = {digest: articles(row) for digest, row in by_sha.items()}
    assigned = defaultdict(list)
    all_articles = sorted(set().union(*map(set, memberships.values())))
    for article in all_articles:
        assigned[article] = []
    multi = []
    for digest, source_ids in memberships.items():
        if len(source_ids) == 1:
            assigned[source_ids[0]].append(digest)
        else:
            multi.append(digest)
    # 多来源图只占一个抽样名额，优先分给独有供给较少的原文；不改图像的真实多来源。
    owners = {}
    for digest in sorted(multi, key=lambda value: (key(seed, "shared-image", value), value)):
        owner = min(memberships[digest], key=lambda article: (len(assigned[article]), key(seed, "article", article), article))
        assigned[owner].append(digest)
        owners[digest] = owner
    for article, digests in assigned.items():
        for digest in digests:
            owners[digest] = article
    order = sorted(all_articles, key=lambda article: (key(seed, "article", article), article))
    pending = {article: deque(sorted(assigned[article], key=lambda digest: (key(seed, "image", digest), digest)))
               for article in order}
    selected, rounds = [], []
    while len(selected) < size:
        round_count = 0
        for article in order:
            if pending[article]:
                digest = pending[article].popleft()
                selected.append({**deepcopy(by_sha[digest]), "sampling_article_id": article,
                                 "sampling_round": len(rounds) + 1, "sampling_rank": len(selected) + 1})
                round_count += 1
                if len(selected) == size:
                    break
        if round_count == 0:
            raise ValueError("配额耗尽但样本未满，池分配有误")
        rounds.append(round_count)
    counts = Counter(row["sampling_article_id"] for row in selected)
    capacities = {article: len(assigned[article]) for article in order}
    distribution = [counts[article] for article in order]
    audit = {"article_count": len(order), "covered_sampling_articles": sum(value > 0 for value in distribution),
             "sample_count": len(selected), "unique_sample_shas": len({row["sha256"] for row in selected}),
             "sample_duplicate_shas": len(selected) - len({row["sha256"] for row in selected}),
             "per_article_min": min(distribution), "per_article_median": statistics.median(distribution),
             "per_article_max": max(distribution), "per_article_count_histogram": dict(sorted(Counter(distribution).items())),
             "round_sizes": rounds, "article_random_order": order,
             "article_allocations": [{"article_id": article, "available_owned_images": capacities[article],
                                      "sampled_images": counts[article], "remaining_owned_images": len(pending[article])}
                                     for article in order],
             "multi_source_image_count": len(multi),
             "multi_source_assignments": [{"sha256": digest, "sampling_article_id": owners[digest],
                                           "all_article_ids": memberships[digest]} for digest in sorted(multi)],
             "empty_after_unique_assignment": [article for article in order if not assigned[article]],
             "exhausted_articles": sum(counts[article] == capacities[article] for article in order)}
    return selected, audit


def old_context(selected: list[dict], paths: list[Path]) -> dict:
    """新有效旧观察优先；失败不覆盖已有有效事实，所有采用项保留源文件及原 JSON 指针。"""
    chosen, history, sources = {}, defaultdict(list), []
    selected_by_id = {row["image_id"]: row for row in selected}
    for path in paths:
        document, source = read(path), ref(path)
        sources.append(source)
        units = ([(f"/units/{index}", unit) for index, unit in enumerate(document["units"])] if "units" in document else
                 [(f"/images/{image_index}/units/{unit_index}", unit)
                  for image_index, row in enumerate(document.get("images", [])) for unit_index, unit in enumerate(row.get("units", []))])
        by_image = defaultdict(list)
        for pointer, unit in units:
            by_image[unit["image_id"]].append((pointer, unit))
        for index, row in enumerate(document.get("images", [])):
            image_id = row["image_id"]
            target = selected_by_id.get(image_id)
            if target is None:
                continue
            original_sha = row.get("sha256") or row.get("image_sha256")
            if original_sha != target["sha256"]:
                raise ValueError(f"旧观察同名图 SHA 不同：{path}:{image_id}")
            item = {"source_ref": source, "image_pointer": f"/images/{index}",
                    "status": row.get("status"), "units": by_image.get(image_id, [])}
            history[image_id].append({key: value for key, value in item.items() if key != "units"})
            if row.get("status") == "observed" or image_id not in chosen:
                chosen[image_id] = item
    output_units, bindings, ledger = [], [], []
    for image in selected:
        image_id = image["image_id"]
        adopted = chosen.get(image_id)
        image_units = adopted["units"] if adopted and adopted["status"] == "observed" else []
        for pointer, unit in image_units:
            if unit.get("image_sha256") != image["sha256"]:
                raise ValueError(f"旧单元未绑定当前原图：{unit['unit_id']}")
            output_units.append(deepcopy(unit))
            bindings.append({"unit_id": unit["unit_id"], "source_ref": adopted["source_ref"], "pointer": pointer})
        ledger.append({"image_id": image_id, "sha256": image["sha256"],
                       "status": adopted["status"] if adopted else "not_previously_observed",
                       "adopted_source": {key: value for key, value in adopted.items() if key != "units"} if adopted else None,
                       "old_observation_history": history.get(image_id, []),
                       "prior_unit_ids": [unit["unit_id"] for _, unit in image_units],
                       "r5_primary_ref_available": bool(image.get("dna_primary_ref"))})
    if len({row["unit_id"] for row in output_units}) != len(output_units):
        raise ValueError("合并旧观察后单元 ID 重复")
    return {"schema_version": "prism.prior_design_observation_context.v1", "source_refs": sources,
            "images": ledger, "units": output_units, "unit_source_bindings": bindings,
            "new_DNA_created": False, "old_observations_modified": False,
            "selection_policy": "later_observed_record_wins;failed_does_not_overwrite_valid;unobserved_keeps_only_existing_R5_refs",
            "counts": {"sample_images": len(selected), "images_with_prior_units": sum(bool(row["prior_unit_ids"]) for row in ledger),
                       "prior_units": len(output_units), "images_with_existing_R5_ref": sum(row["r5_primary_ref_available"] for row in ledger),
                       "adopted_observation_statuses": dict(Counter(row["status"] for row in ledger))}}


def freeze(pool_path: Path, out: Path, *, size: int, seed: str, prior_paths: list[Path], expected_pool_size: int | None = None) -> dict:
    for name in ("sample.json", "sampling-audit.json", "prior-observations.json"):
        if (out / name).exists():
            raise FileExistsError(f"不覆盖既有冻结文件：{out / name}")
    pool, pool_ref = read(pool_path), ref(pool_path)
    if expected_pool_size is not None and len(pool["images"]) != expected_pool_size:
        raise ValueError("输入池数量不符合冻结范围")
    selected, audit = balanced_sample(pool["images"], size, seed)
    validations = []
    for row in selected:
        try:
            actual = sha(Path(row["local_path"]))
            state = "verified" if actual == row["sha256"] else "sha_mismatch"
            error = None
        except (OSError, KeyError) as exc:
            actual, state, error = None, "unreadable", str(exc)
        validations.append({"image_id": row["image_id"], "expected_sha256": row["sha256"], "actual_sha256": actual,
                            "status": state, "error": error})
    # 样本身份先固定；缺图保留失败，不从同篇或其他文章自动找替代图。
    sample = {"schema_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "pool_ref": pool_ref,
              "scope": deepcopy(pool.get("scope", {})),
              "sampling": {"method": "unique_SHA_article_balanced_seeded_round_robin", "seed": seed,
                           "population_size": len(pool["images"]), "sample_size": size,
                           "article_order_key": "SHA256(seed + ':article:' + article_id)",
                           "image_order_key": "SHA256(seed + ':image:' + original_SHA)",
                           "shared_SHA_assignment": "least_owned_article_capacity_then_seeded_article_order",
                           "filters": [], "DNA_quality_category_not_used": True, "missing_images_replaced": False},
              "images": selected}
    prior = old_context(selected, prior_paths)
    audit = {"schema_version": VERSION, "pool_ref": pool_ref, "script_ref": ref(Path(__file__)),
             **audit, "original_byte_checks": validations,
             "original_check_counts": dict(Counter(row["status"] for row in validations)),
             "prior_context_counts": prior["counts"], "new_model_calls": 0}
    write_new(out / "sample.json", sample)
    prior["sample_ref"] = ref(out / "sample.json")
    write_new(out / "prior-observations.json", prior)
    audit["sample_ref"] = ref(out / "sample.json")
    audit["prior_observations_ref"] = ref(out / "prior-observations.json")
    write_new(out / "sampling-audit.json", audit)
    return {key: audit[key] for key in ("pool_ref", "sample_ref", "prior_observations_ref", "sample_count", "article_count",
            "covered_sampling_articles", "per_article_min", "per_article_median", "per_article_max", "per_article_count_histogram",
            "sample_duplicate_shas", "original_check_counts", "prior_context_counts")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--prior-observations", type=Path, action="append", default=[], help="从旧到新传入；不改原文件")
    parser.add_argument("--expected-pool-size", type=int)
    args = parser.parse_args()
    print(json.dumps(freeze(args.pool, args.out, size=args.size, seed=args.seed, prior_paths=args.prior_observations,
                            expected_pool_size=args.expected_pool_size), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

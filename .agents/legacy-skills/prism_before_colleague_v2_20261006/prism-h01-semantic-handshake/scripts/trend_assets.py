"""按文章 ID 关联全部趋势文字与原图清单，只处理元数据和文件路径。"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

INDEX_FILE = "related-trend-articles.json"
INVENTORY_FILE = "frozen/trend-image-inventory.json"
DEFAULT_IMAGES_FILE = "data/trend_data/trend_info_0930/trends.jsonl"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def freeze_inventory(path, root):
    """冻结文章与图片的真实映射；共享图片沿用清单路径，不按文章目录猜测。"""
    path, root = Path(path).resolve(), Path(root).resolve()
    require(path.is_file(), f"图片清单不存在，请配置 trend_images_file: {path}")
    records = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            original_id = str(row["id"])
            require(original_id not in records, f"图片清单文章 ID 重复: {original_id}")
            require(isinstance(row.get("images"), list), f"图片清单需含 images 列表: {original_id}")
            images = []
            for image in row["images"]:
                require(str(image.get("trend_id", original_id)) == original_id, f"图片与文章 ID 不一致: {original_id}")
                local_path = image.get("local_path")
                absolute = (path.parent / local_path).resolve() if local_path else None
                relative = None
                if absolute:
                    try:
                        relative = absolute.relative_to(root).as_posix()
                    except ValueError:
                        relative = str(absolute)
                images.append({
                    "image_id": image.get("image_id"), "index": image.get("index"),
                    "status": image.get("status", "unknown"), "source_url": image.get("url"),
                    "download_url": image.get("download_url"), "local_path": relative,
                    "absolute_local_path": str(absolute) if absolute else None,
                    "format": image.get("format"), "width": image.get("width"),
                    "height": image.get("height"), "size_bytes": image.get("size_bytes"),
                    "sha256": image.get("sha256"), "error": image.get("error"),
                })
            records[original_id] = {"source_title": row.get("title"), "title_zh": row.get("title_zh"),
                                    "source_row": row.get("source_row"), "images": images}
    return {"schema_version": "prism.h01.trend_image_inventory.v1", "project_root": str(root),
            "source_path": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "records": records}


def original_id(article, source_id):
    """优先保留上游原文章 ID；兼容仅有 T:<ID> 的旧文字契约。"""
    value = article.get("original_id")
    return str(value) if value is not None else source_id.removeprefix("T:")


def build_index(snapshot, directions, inventory, snapshot_sha256):
    """输出所有相关簇成员，直接引文只作标记，不限制文章与图片覆盖范围。"""
    membership = defaultdict(list)
    cited = defaultdict(set)
    for direction in directions:
        for cid in direction["trend_cluster_ids"]:
            for sid in snapshot["trend_clusters"][cid]["source_ids"]:
                require(sid in snapshot["articles"], f"趋势成员缺少原文章: {sid}")
                membership[sid].append({"direction_id": direction["direction_id"],
                                        "direction_title": direction["title"],
                                        "decision": direction["decision"], "trend_cluster_id": cid})
        for citation in direction["trend_citations"]:
            evidence = snapshot["evidence"][citation["evidence_id"]]
            cited[evidence["source_id"]].add(evidence["evidence_id"])
    evidence_by_article = defaultdict(list)
    for evidence in snapshot["evidence"].values():
        if evidence["source_id"] in membership:
            evidence_by_article[evidence["source_id"]].append(evidence)
    articles = []
    status_counts = Counter()
    for sid in sorted(membership):
        article = snapshot["articles"][sid]
        oid = original_id(article, sid)
        require(oid in inventory["records"], f"图片清单没有相关原文章: {sid}/{oid}")
        image_record = inventory["records"][oid]
        images = deepcopy(image_record["images"])
        for image in images:
            # 下载状态保留原值；实际文件存在性单独记录，不能把旧成功状态当作文件仍在。
            absolute = image["absolute_local_path"]
            image["file_exists"] = bool(absolute and Path(absolute).is_file())
            image["availability"] = "local" if image["file_exists"] else "missing_local_file" if absolute or image["status"] == "downloaded" else image["status"]
            image["availability_reason"] = None if image["file_exists"] else image.get("error") or (
                "图片清单指向的本地文件不存在" if absolute else "图片清单未提供本地路径")
            status_counts[image["status"]] += 1
            if image["file_exists"]:
                status_counts["local_file_exists"] += 1
        text_evidence = [{
            "evidence_id": e["evidence_id"], "field": e.get("field"), "text": e["text"],
            "text_kind": e["text_kind"], "original_text_excerpt": e.get("original_text_excerpt"),
            "locator": e.get("locator"), "cited_in_handshake": e["evidence_id"] in cited.get(sid, set()),
        } for e in sorted(evidence_by_article[sid], key=lambda e: e["evidence_id"])]
        metadata = article.get("metadata", {})
        articles.append({
            "source_id": sid, "original_id": oid, "title": article.get("title"),
            "source_title": image_record.get("source_title"), "title_zh": image_record.get("title_zh"),
            "source_row": article.get("source_row"), "source_group_id": article.get("source_group_id"),
            "claim_origin_id": article.get("claim_origin_id"), "publisher_group": article.get("publisher_group"),
            "source_url": metadata.get("detail_url") or next((e.get("source_url") for e in evidence_by_article[sid] if e.get("source_url")), None),
            "metadata": metadata, "direction_membership": sorted(membership[sid], key=lambda m: (m["direction_id"], m["trend_cluster_id"])),
            "text_evidence": text_evidence, "images": images,
        })
    total_images = sum(len(a["images"]) for a in articles)
    stats = {
        "related_trend_clusters": len({m["trend_cluster_id"] for a in articles for m in a["direction_membership"]}),
        "related_directions": len(directions), "related_articles": len(articles),
        "directly_cited_articles": len(cited), "directly_cited_evidence_ids": sum(map(len, cited.values())),
        "article_text_evidence_records": sum(len(a["text_evidence"]) for a in articles),
        "image_references": total_images, "local_image_references": status_counts["local_file_exists"],
        "unresolved_image_references": total_images - status_counts["local_file_exists"],
        "image_status_counts": dict(status_counts),
    }
    return {
        "schema_version": "prism.h01.related_trend_articles.v1", "snapshot_sha256": snapshot_sha256,
        "image_inventory_source": {"path": inventory["source_path"], "sha256": inventory["source_sha256"]},
        "association_rule": "按趋势簇 source_id 与原文章 original_id 关联全部文字及图片，路径来自冻结图片清单；共用原图保留同一路径。",
        "scope_note": "所有相关簇成员文章的标题/摘要与来源索引；非全部已证明支持握手的证据。完整网页正文未采集，图片未参与语义判断。",
        "stats": stats, "articles": articles,
    }


def attach_direction_assets(directions, assets):
    """主结果按方向提供完整文章列表和图片索引入口，图片清单独立存储避免重复膨胀。"""
    related = defaultdict(list)
    for article in assets["articles"]:
        for did in {m["direction_id"] for m in article["direction_membership"]}:
            related[did].append(article)
    enriched = []
    for direction in directions:
        articles = related[direction["direction_id"]]
        images = [image for a in articles for image in a["images"]]
        local_count = sum(image["file_exists"] for image in images)
        enriched.append({**direction, "related_trend_assets": {
            "index_file": INDEX_FILE, "article_source_ids": [a["source_id"] for a in articles],
            "article_count": len(articles), "image_reference_count": len(images),
            "local_image_count": local_count, "unresolved_image_count": len(images) - local_count,
        }})
    return enriched

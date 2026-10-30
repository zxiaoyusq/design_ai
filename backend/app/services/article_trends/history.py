"""只读展示旧版归并成果；字段投影不代表按新版规则重新聚类或复核。"""

from collections import Counter
import json
from pathlib import Path
from threading import RLock

from app.services.article_trends.catalog import PROJECT, ArticleCatalog


HISTORY_ID = "astra-consensus-20261001"
HISTORY_PATH = Path("data/result/trend_text_clusters/astra_consensus_20261001/final")
EVIDENCE_LIMIT = 8
LEGACY_NOTICE = (
    "这是 2026-10-01 按旧版最多 100 个趋势规则形成的历史归并结果，保持原排序与原计数，"
    "未按当前无数量上限的 Skill 3.0 重新运行。来源组与文章数沿用旧版点级归并口径，"
    "不等同于新版独立复核通过的主/次成员支持数；原状态为待人工审阅。"
)
COUNTING_NOTE = "原归并来源组数/文章数；一篇文章可关联多个趋势，不是新版 supported 主成员数。"


class HistoricalTrendResults:
    """仅暴露登记过的历史批次；不扫描用户提供的目录，也不写入任何历史文件。"""

    def __init__(self, root: Path = PROJECT, catalog: ArticleCatalog | None = None):
        self.directory = root / HISTORY_PATH
        self.catalog = catalog if catalog is not None else ArticleCatalog(root)
        self._lock = RLock()
        self._signature = None
        self._result = None
        self._image_members = {}

    def _check_id(self, history_id: str):
        if history_id != HISTORY_ID:
            raise FileNotFoundError("历史批次不存在")

    def _read(self, filename: str):
        try:
            return json.loads((self.directory / filename).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("历史结果文件格式异常") from exc

    def _metadata(self):
        summary, execution = self._read("summary.json"), self._read("execution.json")
        compiled_at = execution["compiled_at"]
        return {
            "id": HISTORY_ID, "kind": "historical", "title": f"历史归并结果 · {summary['main_trends']} 个趋势",
            "status": "completed", "stage": "历史结果（待人工审阅）",
            # 旧执行档未记录网页任务步数与总调用数，未知值不能被包装成零消耗。
            "completed_steps": None, "total_steps": None, "calls": None,
            "model_id": execution.get("selection_analysis", {}).get("model_id"),
            "skill_version": f"legacy-consensus-{execution['version']}",
            "min_source_groups": summary.get("min_source_groups"),
            "article_count": summary["articles"], "trend_count": summary["main_trends"],
            "created_at": compiled_at, "updated_at": compiled_at, "error": None,
            "review_status": summary["review_status"], "legacy_notice": LEGACY_NOTICE,
            "download_url": f"/api/v1/article-trends/history/{HISTORY_ID}/download",
            "download_label": "下载历史趋势原档（完整证据）",
            "download_description": "原始 trend-clusters.json，含全部趋势、成员点与归并沿革；不含另存的候选池及覆盖旁表。",
        }

    def list(self):
        if not (self.directory / "summary.json").is_file():
            return []
        return [self._metadata()]

    @staticmethod
    def _member(point: dict, articles: dict):
        evidence_id = point.get("evidence_id", "")
        source_id = evidence_id.rsplit(":", 1)[0]
        article = articles.get(source_id, {})
        return {
            "article_id": article.get("original_id"), "title": article.get("title", source_id),
            "source_id": source_id, "point_id": point.get("point_id"), "evidence_id": evidence_id,
            "anchor": point.get("quote", ""), "reason": point.get("reason", ""),
            "condition": point.get("condition"), "feature": point.get("feature"),
            "effective_feature": point.get("effective_feature"),
            "rejected_inference": point.get("rejected_inference"),
            "source_group_id": article.get("source_group_id"), "review_status": "pending_human_review",
        }

    def _project(self):
        source = self._read("trend-clusters.json")
        articles = {row["source_id"]: row for row in self._read("trend-catalogue.json")["articles"]}
        trends, image_members = [], {}
        for rank, cluster in enumerate(source["clusters"], start=1):
            # lineage 还保留继承信息，只展示确实归入本簇的点，避免把旧父簇其他成员带回来。
            selected = set(cluster["point_ids"])
            members, related_articles, seen_articles, seen_points = [], [], set(), set()
            for seed in cluster.get("lineage", []):
                for point in seed.get("members", []):
                    if point.get("point_id") not in selected or point["point_id"] in seen_points:
                        continue
                    seen_points.add(point["point_id"])
                    member = self._member(point, articles)
                    if member["source_id"] not in seen_articles:
                        seen_articles.add(member["source_id"])
                        related_articles.append(member)
                        if len(members) < EVIDENCE_LIMIT:
                            members.append(member)
            # 图片可以来自完整成员集，不能受文字代表证据的前八篇截断影响。
            image_members[cluster["cluster_id"]] = related_articles
            trends.append({
                "theme_id": cluster["cluster_id"], "title": cluster["title"],
                "definition": cluster["definition"], "design_question": cluster.get("design_question", ""),
                "boundary": "；".join(cluster.get("boundaries", {}).get("excludes", [])),
                "boundaries": cluster.get("boundaries", {}), "priority_rank": rank,
                "source_group_count": cluster["source_group_count"], "article_count": cluster["source_article_count"],
                "members": members, "members_displayed": len(members),
                "evidence_point_count": len(selected), "evidence_truncated": len(selected) > len(members),
                "evidence_display_note": f"按原沿革顺序展示最多 {EVIDENCE_LIMIT} 篇去重文章的原证据；完整成员点及沿革见历史原档下载。",
                "counting_note": COUNTING_NOTE, "review_status": source["review_status"],
                "unknowns": cluster.get("unknowns", []), "variations": cluster.get("variations", []),
                "legacy_counts": {key: cluster[key] for key in ("source_group_count", "source_article_count")},
            })
        pool = [{
            **self._member(point, articles),
            "theme_id": point["point_id"], "title": point.get("feature", point.get("subject", "历史候选线索")),
            "pool_reason": point.get("deferred_reason", point.get("reason_code", "")),
        } for point in self._read("evidence-pool.json")["points"]]
        coverage = self._read("coverage.json")
        result = {
            "kind": "historical", "version": source["schema_version"], "trends": trends,
            "evidence_pool": pool, "legacy_notice": LEGACY_NOTICE, "counting_note": COUNTING_NOTE,
            "review_status": source["review_status"], "visual_analysis_performed": source["visual_analysis_performed"],
            "legacy_summary": self._read("summary.json"),
            "coverage": {
                "article_count": len(coverage), "legacy_status_counts": dict(Counter(row["status"] for row in coverage)),
                "deferred_point_count": len(pool), "review_status": source["review_status"],
                "note": "旧版覆盖状态汇总，不转换成新版 supported/uncertain/unsupported 复核判定。",
            },
        }
        return result, image_members

    def _images(self, members):
        images, candidates, seen_articles, seen_urls, seen_hashes = [], [], set(), set(), set()

        def append(article, image):
            key = image["source_url"] or image["url"]
            digest = image["source_sha256"]
            if key in seen_urls or (digest and digest in seen_hashes):
                return False
            seen_urls.add(key)
            if digest:
                seen_hashes.add(digest)
            images.append({
                "article_id": str(article["article_id"]), "article_title": article["title"],
                "image_id": image["image_id"], "url": image["url"],
            })
            return True

        # 先让不同关联文章各贡献一张，再用其余已有图片补足展示容量。
        for member in members:
            aid = member["article_id"]
            if aid is None or str(aid) in seen_articles:
                continue
            seen_articles.add(str(aid))
            available = self.catalog.available_images(str(aid))
            candidates.append((member, available))
            for image in available:
                if append(member, image):
                    break
            if len(images) == EVIDENCE_LIMIT:
                return images
        for member, available in candidates:
            for image in available:
                append(member, image)
                if len(images) == EVIDENCE_LIMIT:
                    return images
        return images

    def get(self, history_id: str):
        self._check_id(history_id)
        filenames = ("summary.json", "execution.json", "trend-clusters.json", "trend-catalogue.json", "evidence-pool.json", "coverage.json")
        with self._lock:
            signature = tuple((path.stat().st_mtime_ns, path.stat().st_size) for path in (self.directory / name for name in filenames))
            if signature != self._signature:
                self._result, self._image_members = self._project()
                self._signature = signature
            # 文字投影可缓存，图片每次沿现有索引核对文件，以响应下载完成、移除或索引更新。
            result = {**self._result, "trends": [
                {**trend, "images": self._images(self._image_members[trend["theme_id"]])}
                for trend in self._result["trends"]
            ]}
            return {**self._metadata(), "result": result}

    def download_path(self, history_id: str):
        self._check_id(history_id)
        path = self.directory / "trend-clusters.json"
        if not path.is_file():
            raise FileNotFoundError("历史结果不存在")
        return path

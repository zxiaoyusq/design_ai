"""将已冻结的原生 H01 结果只读投影到网页，保留证据角色和完整图片关联。"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from PIL import Image, ImageOps


PROJECT_ROOT = Path(__file__).resolve().parents[4]
RESULT_ID = "sol61-native-v2-20261006"
RUN_RELATIVE_PATH = Path("data/result/semantic_handshake/sol61_native_v2_20261006")


class NativeResultError(ValueError):
    """原生文件缺失、绑定失效或图片路径不合法时拒绝提供替代结果。"""


def _digest(value: dict) -> str:
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class NativeHighTrendResult:
    """仅注册本次真实运行，不接受请求方指定任意结果目录。"""

    result_id = RESULT_ID

    def __init__(self, root: Path | str = PROJECT_ROOT):
        self.root = Path(root).resolve()
        self.run = self.root / RUN_RELATIVE_PATH
        self._lock = RLock()
        self._signature = None
        self._task: dict | None = None
        self._images: dict[str, dict] = {}
        self._direction_images: dict[str, list[dict]] = {}
        self._validated_images: dict[str, tuple] = {}
        self._paths = {
            "accepted": self.run / "h01-run/accepted.json",
            "candidates": self.run / "h01-run/candidate-directions.json",
            "selection": self.run / "h01-run/selection.json",
            "execution": self.run / "execution-receipt.json",
            "sources": self.run / "related-trend-articles.json",
            "decision_log": self.run / "direction-selection/decision-log.json",
            "markdown": self.run / "report.md",
        }

    @staticmethod
    def _need(condition, message: str):
        if not condition:
            raise NativeResultError(message)

    def _load(self):
        with self._lock:
            try:
                signature = tuple((name, path.stat().st_mtime_ns, path.stat().st_size) for name, path in self._paths.items())
            except OSError as exc:
                raise NativeResultError("原生高潜结果文件不存在，无法读取本次结果") from exc
            if signature == self._signature:
                return
            try:
                files = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in self._paths.items() if name != "markdown"}
            except (OSError, ValueError) as exc:
                raise NativeResultError("原生高潜结果文件无法解析") from exc
            hashes = {name: _sha(path) for name, path in self._paths.items()}
            accepted, candidates, selection = (files[k] for k in ("accepted", "candidates", "selection"))
            for name, artifact in (("接受稿", accepted), ("候选方向", candidates), ("选向", selection)):
                self._need(artifact.get("digest") == _digest({k: v for k, v in artifact.items() if k != "digest"}), f"{name}摘要校验不匹配")
            self._need(files["sources"].get("accepted_sha256") == hashes["accepted"], "图片来源清单与接受稿 SHA 不匹配")
            self._need(selection.get("candidate_digest") == candidates["digest"], "选向结果与候选方向摘要不匹配")
            self._need(accepted.get("workflow_candidates") == candidates, "接受稿与候选方向内容不匹配")
            decisions = files["decision_log"]
            for field, name in (("acceptedFileRef", "accepted"), ("candidateFileRef", "candidates"), ("selection_ref", "selection")):
                self._need(decisions.get(field, {}).get("sha256") == hashes[name], f"选向日志与{name}文件 SHA 不匹配")
            confirmation = selection.get("confirmation", {})
            self._need(confirmation.get("candidate_digest") == candidates["digest"], "选向确认绑定的候选摘要不匹配")
            directions = candidates.get("directions", [])
            ids = [row["direction_id"] for row in directions]
            self._need(len(set(ids)) == len(ids), "原生候选方向 ID 重复")
            selected = {row["direction_id"]: row.get("branches", []) for row in selection.get("selection", [])}
            self._need(set(selected).issubset(ids), "选向结果包含不存在的方向")
            self._images, self._direction_images = {}, {key: [] for key in ids}
            articles = files["sources"].get("articles", [])
            article_index = {row["source_id"]: row for row in articles}
            cited_sources = {
                row["direction_id"]: {citation["evidence_id"].rsplit(":", 1)[0] for citation in row.get("trend_citations", [])}
                for row in directions
            }
            for article in articles:
                memberships = [m["direction_id"] for m in article.get("direction_membership", []) if m.get("direction_id") in ids]
                for original in article.get("images", []):
                    key_input = str(original.get("image_id", "")) + "\n" + str(original.get("local_path") or original.get("absolute_local_path") or original.get("url", ""))
                    key = hashlib.sha256(key_input.encode()).hexdigest()
                    local = self._safe_image_path(original)
                    existing = self._images.get(key)
                    if existing is None:
                        existing = {
                            "native_image_key": key,
                            "image_id": original.get("image_id"),
                            "sha256": original.get("sha256"),
                            "file_exists": local is not None and local.is_file(),
                            "source_record_id": article["source_id"],
                            "article_title": article.get("title", ""),
                            "article_url": article.get("metadata", {}).get("detail_url"),
                            "image_url": original.get("url"),
                            "width": original.get("width"),
                            "height": original.get("height"),
                            "byte_size": original.get("size_bytes"),
                            "direction_ids": [],
                            "source_path": original.get("local_path"),
                            "_path": local,
                        }
                        if existing["file_exists"]:
                            base = f"/api/v1/high-trends/native-results/{RESULT_ID}/images/{key}"
                            existing.update(url=base + "?thumbnail=true", original_url=base)
                        else:
                            existing.update(url=None, original_url=None)
                        self._images[key] = existing
                    for direction_id in memberships:
                        if direction_id not in existing["direction_ids"]:
                            existing["direction_ids"].append(direction_id)
                        if not any(item["native_image_key"] == key for item in self._direction_images[direction_id]):
                            self._direction_images[direction_id].append({
                                **existing,
                                "association_type": "cited" if article["source_id"] in cited_sources[direction_id] else "associated",
                            })
            # 一个来源图片可能被多个方向引用；最终列表共享完整归属，不能被最后一次遍历覆盖。
            for rows in self._direction_images.values():
                for item in rows:
                    item["direction_ids"] = self._images[item["native_image_key"]]["direction_ids"][:]
                rows.sort(key=lambda item: item["association_type"] != "cited")
            decision_index = {row["direction_id"]: row for row in decisions.get("decisions", [])}
            people = {str(e["person_id"]) for row in directions for e in row.get("research_original_evidence", []) if e.get("person_id") is not None}
            cards = [self._card(row, selected, decision_index, article_index, len(people)) for row in directions]
            execution = files["execution"]
            completed = execution.get("completed_at", "")
            provenance = {
                "model_id": execution.get("semantic_analyst_model_id"),
                "exact_model_version": execution.get("exact_model_version"),
                "algorithm_version": execution.get("algorithm_version"),
                "prompt_version": execution.get("prompt_version"),
                "prompt_sha256": execution.get("prompt_sha256"),
                "run_started_at": execution.get("run_started_at"),
                "completed_at": completed,
                "semantic_truth_verified": accepted.get("semantic_truth_verified", False),
                "image_analysis_performed": execution.get("image_analysis_performed", False),
                "selection_actor": confirmation.get("actor_kind"),
                "actor": confirmation.get("actor_kind"),
                "confirmed_at": confirmation.get("confirmed_at"),
                "selection_confirmation": deepcopy(confirmation),
                "candidate_digest": candidates["digest"],
                "selected_count": len(selected),
                "direction_count": len(cards),
                "token_usage": execution.get("token_usage"),
                "scope_note": files["sources"].get("scope_note", ""),
                "file_refs": [{"role": name, "path": str(path), "sha256": hashes[name]} for name, path in self._paths.items()],
            }
            self._task = {
                "id": RESULT_ID, "kind": "native_h01", "status": "completed", "stage": "completed",
                "message": "已载入本次原生高潜结果", "completed_jobs": 0, "total_jobs": 0,
                "created_at": execution.get("run_started_at", ""), "updated_at": completed,
                "title": "高潜趋势 · 6.1 Sol 原生握手", "direction_count": len(cards),
                "selected_count": len(selected), "exploratory_count": len(cards) - len(selected),
                # 本次宿主模型调用预算未公开，不补造网页任务的 max_calls 数值。
                "request": {"input_mode": "module_outputs", "model_id": execution.get("semantic_analyst_model_id")},
                "provenance": provenance, "events": [],
                "result": {
                    "trends": cards, "user_research_gaps": {"directions": []}, "warnings": [],
                    "scope_note": files["sources"].get("scope_note", ""), "has_content": bool(cards), "partial": False,
                },
            }
            self._signature = signature
            self._validated_images.clear()

    def _safe_image_path(self, item: dict) -> Path | None:
        value = item.get("local_path") or item.get("absolute_local_path")
        if not value:
            return None
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        # 原图仅从当前项目的趋势图片目录读取，拒绝 ../、符号链接及任意绝对路径越界。
        return resolved if resolved.is_relative_to(self.root / "data/trend_data/images") else None

    @staticmethod
    def _public_image(item: dict) -> dict:
        return {key: value for key, value in item.items() if not key.startswith("_")}

    def _card(self, direction: dict, selected: dict, decisions: dict, article_index: dict, population: int) -> dict:
        direction_id = direction["direction_id"]
        decision = decisions.get(direction_id, {})
        originals = {row["unit_id"]: row for row in direction.get("research_original_evidence", [])}
        research = []
        for citation in direction.get("research_citations", []):
            original = originals.get(citation["unit_id"], {})
            research.append({
                **deepcopy(citation), "person_id": original.get("person_id"),
                "source_kind": original.get("source_kind"), "source_channel": original.get("source_channel"),
                "source_attitude": original.get("source_attitude"), "object_scope": deepcopy(original.get("source_scope", {})),
                "original_text": original.get("text"), "source_id": original.get("source_id"),
                "source_slide_id": original.get("source_slide_id"), "source_page": original.get("source_page"),
            })
        trend_originals = {row["evidence_id"]: row for row in direction.get("trend_original_evidence", [])}
        trends = []
        for citation in direction.get("trend_citations", []):
            original = trend_originals.get(citation["evidence_id"], {})
            source_id = original.get("source_id") or citation["evidence_id"].rsplit(":", 1)[0]
            article = article_index.get(source_id, {})
            trends.append({**deepcopy(citation), "source_id": source_id,
                           "title": article.get("title", ""), "url": article.get("metadata", {}).get("detail_url") or original.get("source_url"),
                           "original_text": original.get("text"), "text_kind": original.get("text_kind", citation.get("text_kind")),
                           "locator": deepcopy(original.get("locator"))})
        articles = [row for row in article_index.values() if any(m.get("direction_id") == direction_id for m in row.get("direction_membership", []))]
        direct_ids = {row["source_id"] for row in trends}
        source_records = [{"short_id": row["source_id"], "record_id": row["source_id"], "kind": "trend", "title": row.get("title"),
                           "source_path": row.get("metadata", {}).get("detail_url")} for row in articles if row["source_id"] in direct_ids]
        rows = self._direction_images[direction_id]
        counts = Counter(item.get("state") for item in direction.get("negative_scope_audit", []))
        conditions = deepcopy(direction.get("conditions_and_limits", []))
        unresolved = deepcopy(direction.get("unresolved_questions", []))
        cited = [self._public_image(item) for item in rows if item["association_type"] == "cited"]
        associated = [self._public_image(item) for item in rows if item["association_type"] == "associated"]
        detail = {
            "design_question": direction.get("design_question", ""), "selected": direction_id in selected,
            "selected_branches": selected.get(direction_id, []), "suggested_branches": direction.get("suggested_branches", []),
            "selection_reason": decision.get("reason", ""), "branch_rationale": decision.get("branch_rationale", ""),
            "recommendation": decision.get("recommendation"), "extension_explanation": direction.get("extension_explanation", ""),
            "hypotheses": deepcopy(direction.get("hypotheses", [])), "research_citations": research, "trend_citations": trends,
            "conditions": conditions, "unresolved_questions": unresolved,
            "negative_counts": {key: counts[key] for key in ("applicable", "unresolved", "not_applicable")},
            "source_article_count": len(articles), "direct_article_count": sum(row["source_id"] in direct_ids for row in articles),
            "total_image_count": len(rows), "cited_image_count": len(cited), "associated_image_count": len(associated),
            "missing_image_count": sum(not item["file_exists"] for item in rows),
            "preview_images": [self._public_image(item) for item in rows[:12]],
            "original_cluster_ids": deepcopy(direction.get("original_cluster_ids", {})),
            "direct_support_person_ids": direction.get("direct_support_person_ids", []),
            "people_by_evidence_role": deepcopy(direction.get("people_by_evidence_role", {})),
            "alignment_state": direction.get("alignment_state"),
        }
        return {
            "id": direction_id, "title": direction["title"], "description": direction.get("design_question", ""),
            "relation_basis": direction.get("relation_basis", "unknown"),
            "shared_design_principle": direction.get("shared_design_principle", ""),
            "conditions_and_limits": "\n".join(item.get("implication") or item.get("text", "") for item in conditions),
            "unresolved_questions": "\n".join(unresolved), "source_records": source_records,
            "associated_source_records": [], "image_refs": cited[:12], "associated_image_refs": associated[:12],
            "mention_statistics": {"unique_mentioned_users": len(direction.get("direct_support_person_ids", [])), "population_count": population,
                                   "note": "仅按直接支持证据去重计人数；其他角色不计为支持人数，不代表偏好率。"},
            "trend_coverage_note": "同簇文章和图片仅保留关联；图片未经过本轮视觉验证。",
            "evidence_review_status": "native_semantic_candidates", "native_detail": detail,
        }

    def metadata(self) -> dict:
        self._load()
        return deepcopy({key: value for key, value in self._task.items() if key != "result"})

    def get(self) -> dict:
        self._load()
        return deepcopy(self._task)

    def images(self, direction_id: str, page: int = 1, page_size: int = 60, scope: str = "all") -> dict:
        self._load()
        self._need(direction_id in self._direction_images, "高潜方向不存在")
        self._need(scope in ("all", "cited", "associated"), "图片关联范围不合法")
        self._need(isinstance(page, int) and page > 0 and isinstance(page_size, int) and 1 <= page_size <= 100, "图片分页参数不合法")
        rows = self._direction_images[direction_id]
        if scope != "all":
            rows = [row for row in rows if row["association_type"] == scope]
        start = (page - 1) * page_size
        return {"items": [deepcopy(self._public_image(row)) for row in rows[start:start + page_size]],
                "total": len(rows), "page": page, "page_size": page_size, "scope": scope}

    def image(self, key: str, thumbnail: bool = False) -> Path:
        self._load()
        self._need(key in self._images, "原生结果图片不存在")
        item = self._images[key]
        path = item["_path"]
        self._need(path is not None and path.is_file(), "原始图片文件不存在或路径不允许访问")
        # 请求时再次解析，防止缓存建立后目录被符号链接替换。
        self._need(path.resolve().is_relative_to(self.root / "data/trend_data/images"), "图片路径越界")
        stat = path.stat()
        signature = (str(path), stat.st_size, stat.st_mtime_ns, item.get("sha256"))
        with self._lock:
            if self._validated_images.get(key) != signature:
                if item.get("sha256"):
                    self._need(_sha(path) == item["sha256"], "原始图片 SHA 校验不匹配")
                self._validated_images[key] = signature
            if not thumbnail:
                return path
            cache_key = hashlib.sha256(repr(signature).encode()).hexdigest()
            cache = self.root / ".runtime/high-trends-native-thumbnails" / (cache_key + ".webp")
            if cache.is_file():
                return cache
            cache.parent.mkdir(parents=True, exist_ok=True)
            try:
                with Image.open(path) as original:
                    preview = ImageOps.exif_transpose(original)
                    preview.thumbnail((640, 640))
                    if preview.mode not in ("RGB", "RGBA"):
                        preview = preview.convert("RGB")
                    with tempfile.NamedTemporaryFile(dir=cache.parent, suffix=".webp", delete=False) as temporary:
                        temporary_path = Path(temporary.name)
                    try:
                        preview.save(temporary_path, "WEBP", quality=80)
                        os.replace(temporary_path, cache)
                    finally:
                        temporary_path.unlink(missing_ok=True)
            except (OSError, ValueError) as exc:
                raise NativeResultError("原始图片无法生成预览") from exc
            return cache

    def download(self, format: str = "json") -> Path:
        self._load()
        roles = {"json": "accepted", "selection": "selection", "sources": "sources", "markdown": "markdown"}
        self._need(format in roles, "不支持的原生结果下载格式")
        return self._paths[roles[format]]

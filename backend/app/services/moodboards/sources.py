"""只读解析高潜结果中的趋势图片，冻结真实文件身份后交给视觉聚类。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from app.services.high_trends.native_result import NativeHighTrendResult


PROJECT_ROOT = Path(__file__).resolve().parents[4]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
REFERENCE_FIELDS = {
    "image_refs": "direct_reference",
    "associated_image_refs": "same_cluster_association",
    "visual_extension_image_refs": "visual_extension",
}


def _read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _rejected(item):
    """只认明确排除；未审阅、缺分数和模型不确定不等同于人工拒绝。"""
    review = item.get("human_review") or {}
    if not isinstance(review, dict):
        review = {"status": review}
    states = [item.get("review_status"), item.get("human_review_status"),
              review.get("status"), review.get("decision")]
    dislike = "DISLIKE" in re.findall(r"[A-Z]+", str(item.get("emotion_tag", "")).upper())
    for origin in item.get("origins", []):
        if origin.get("source_kind") == "user":
            tags = [origin.get("emotion_tag", "")] + [row.get("emotion_tag", "")
                                                       for row in origin.get("feedback", [])]
            dislike |= any("DISLIKE" in re.findall(r"[A-Z]+", str(tag).upper()) for tag in tags)
            dislike |= isinstance(origin.get("dislike_count"), (int, float)) and origin["dislike_count"] > 0
    return item.get("retained") is False or dislike or any(
        str(state).upper() in {"FAIL", "REJECT", "REJECTED", "EXCLUDED"} for state in states)


class MoodboardSources:
    """输入只接受已登记结果 ID；目录可选，实际选材才读取图片并按 SHA 去重。"""

    def __init__(self, root=PROJECT_ROOT, native_results=None):
        self.root = Path(root).resolve()
        self.output = self.root / "data/result/high_trend"
        # 注入注册源便于离线验证；HTTP 请求不能传入目录或自建注册源。
        native = NativeHighTrendResult(self.root)
        self.native_results = ({native.result_id: native} if native_results is None
                               else dict(native_results))

    def _inside_data(self, path):
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.root / "data"):
            raise ValueError("来源路径超出项目 data 目录")
        return resolved

    def _web(self, result_id):
        if not re.fullmatch(r"web_[a-f0-9]{32}", result_id):
            raise FileNotFoundError("高潜趋势结果未登记")
        folder = self._inside_data(self.output / result_id)
        task = _read(self._inside_data(folder / "web_task.json"))
        if task.get("status") not in {"completed", "partial"}:
            raise ValueError("请选择已完成或已有部分结果的高潜趋势任务")
        result_path = self._inside_data(folder / "high_potential_trends.json")
        result = _read(result_path)
        return {**task, "id": result_id, "kind": "web", "result": result}, folder

    def _load(self, result_id):
        if result_id in self.native_results:
            task = self.native_results[result_id].get()
            if task.get("status") not in {"completed", "partial"}:
                raise ValueError("原生高潜结果尚未完成")
            return {**task, "id": result_id, "kind": "native_h01"}, None
        return self._web(result_id)

    @staticmethod
    def _cards(task):
        result = task["result"]
        cards = result.get("trends", []) + result.get("user_research_gaps", {}).get("directions", [])
        ids = [card["id"] for card in cards]
        if len(ids) != len(set(ids)):
            raise ValueError("高潜结果方向 ID 重复，不能确定选材范围")
        return cards

    @staticmethod
    def _direction(card):
        count = card.get("native_detail", {}).get("total_image_count")
        if count is None:
            count = sum(len(card.get(field, [])) for field in REFERENCE_FIELDS)
        return {"id": card["id"], "title": card.get("title", ""),
                "description": card.get("description", ""), "image_reference_count": count}

    def _metadata(self, task):
        return {"id": task["id"], "kind": task["kind"], "status": task["status"],
                "title": task.get("title") or f"高潜趋势 · {task.get('created_at', task['id'])}",
                "created_at": task.get("created_at", ""),
                "directions": [self._direction(card) for card in self._cards(task)]}

    def catalog(self):
        """只读结果 JSON 和文件索引；不构造旧任务管理器或扫描原图库。"""
        results, warnings = [], []
        ids = [path.parent.name for path in sorted(self.output.glob("web_*/web_task.json"))]
        for result_id in ids + list(self.native_results):
            try:
                task, _ = self._load(result_id)
                metadata = self._metadata(task)
                if metadata["directions"]:
                    results.append(metadata)
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(f"{result_id} 暂不可选：{exc}")
        return {"results": sorted(results, key=lambda item: item["created_at"], reverse=True),
                "warnings": warnings}

    def _web_reviews(self, folder, result_id, warnings):
        path = self._inside_data(folder / "image_review/review.json")
        if not path.exists():
            return {}, None
        review = _read(path)
        if review.get("task_id") != result_id:
            raise ValueError("人工图片选择与高潜结果 ID 不匹配，请先核对原人工记录")
        bound = review.get("source_result_sha256")
        if bound and bound != _sha(self._inside_data(folder / "high_potential_trends.json")):
            warnings.append("人工选图绑定的是旧版结果；仍按真实图片 SHA 保留其排除，不自动恢复被拒绝图片。")
        rows = {}
        for item in review.get("images", []) + review.get("excluded_user_dislike_images", []):
            digest = item.get("sha256")
            if digest:
                old = rows.get(digest)
                # 同一指纹冲突时采用明确拒绝，不以最后一条覆盖掉人工否决。
                if old is None or _rejected(item):
                    rows[digest] = item
        return rows, {"path": str(path), "sha256": _sha(path),
                      "revision": review.get("revision"), "source_result_sha256": bound}

    def _references(self, result_id, cards, folder, all_cards):
        if folder is None:
            native = self.native_results[result_id]
            for card in cards:
                page = 1
                while True:
                    batch = native.images(card["id"], page=page, page_size=100, scope="all")
                    for ref in batch["items"]:
                        yield card, ref, ref.get("association_type", "associated"), True
                    if page * 100 >= batch["total"]:
                        break
                    if not batch["items"]:
                        raise ValueError("原生高潜图片分页不完整")
                    page += 1
            return
        sources_path = self._inside_data(folder / "sources.json")
        sources = _read(sources_path) if sources_path.exists() else {}
        selected = {card["id"] for card in cards}
        image_index = -1
        for card in all_cards:
            trend_ids = {source.get("record_id") for source in
                         card.get("source_records", []) + card.get("associated_source_records", [])
                         if source.get("kind") == "trend"}
            for field, association in REFERENCE_FIELDS.items():
                for ref in card.get(field, []):
                    image_index += 1
                    if card["id"] not in selected:
                        continue
                    aliases = ref.get("evidence_ids", [])
                    matched = [(key, value) for key, value in sources.items()
                               if key in aliases or value.get("id") == ref.get("source_record_id")]
                    is_trend = (ref.get("role") == "trend_reference"
                                or any(value.get("kind") == "trend" for _, value in matched)
                                or ref.get("source_record_id") in trend_ids)
                    kind = ("trend" if is_trend else "user" if
                            any(str(value.get("kind", "")).startswith("user") for _, value in matched)
                            or str(ref.get("role", "")).startswith("user") else "unknown")
                    project_ids = {value.get("project_id") or value.get("fields", {}).get("project_id")
                                   for _, value in matched}
                    project_ids.discard(None)
                    enriched = {**ref, "source_kind": kind,
                                "project_id": ref.get("project_id") or (next(iter(project_ids)) if len(project_ids) == 1 else None),
                                "preview_url": f"/api/v1/high-trends/tasks/{result_id}/images/{image_index}",
                                "source_aliases": [key for key, _ in matched],
                                "source_records": [{"alias": key,
                                    **{field: value.get(field) for field in
                                       ("id", "kind", "source_file", "json_pointer", "user_id", "project_id")},
                                    "title": value.get("fields", {}).get("title_zh")}
                                    for key, value in matched]}
                    yield card, enriched, association, is_trend

    def _path(self, result_id, ref, native):
        if native:
            path = self._inside_data(self.native_results[result_id].image(ref["native_image_key"]))
        else:
            raw = (ref.get("absolute_path") or ref.get("path") or ref.get("declared_path")
                   or ref.get("local_path"))
            if not raw:
                raise FileNotFoundError("未声明本地原图路径")
            path = Path(raw)
            path = self._inside_data(path if path.is_absolute() else self.root / path)
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
            raise FileNotFoundError("原图缺失或格式不受支持")
        return path

    def _source_refs(self, task, folder):
        if folder:
            paths = [folder / name for name in (
                "web_task.json", "high_potential_trends.json", "sources.json", "image_review/review.json")]
        else:
            paths = [Path(binding["path"]) for binding in task.get("provenance", {}).get("file_refs", [])]
        paths = [self._inside_data(path) for path in paths]
        return [{"path": str(path), "sha256": _sha(path)} for path in paths if path.is_file()]

    def scope(self, result_id, direction_ids):
        """合并所选方向实际关联图片；方向仅限定来源，不作为视觉聚类类别。"""
        task, folder = self._load(result_id)
        source_refs = self._source_refs(task, folder)
        # 先绑定再读取实际范围，最后复核；人工选择或结果重编译不能混入同一份快照。
        task, folder = self._load(result_id)
        wanted = list(dict.fromkeys(direction_ids))
        all_cards = self._cards(task)
        if not wanted or not set(wanted).issubset({card["id"] for card in all_cards}):
            raise ValueError("请选择本次高潜结果中存在的方向")
        cards = [card for card in all_cards if card["id"] in wanted]
        warnings = list(task["result"].get("warnings", []))
        if task["status"] == "partial":
            warnings.append("所选高潜结果为部分完成；仅使用已经保存的方向图片。")
        reviews, review_binding = self._web_reviews(folder, result_id, warnings) if folder else ({}, None)
        missing, excluded, by_hash = [], [], {}
        references = valid_references = 0
        for card, ref, association, is_trend in self._references(result_id, cards, folder, all_cards):
            references += 1
            origin = {"result_id": result_id, "direction_id": card["id"],
                      "direction_title": card.get("title", ""), "association_type": association,
                      "image_id": ref.get("image_id"), "source_record_id": ref.get("source_record_id"),
                      "source_kind": "trend" if folder is None else ref.get("source_kind", "unknown"),
                      "article_id": ref.get("source_record_id") if is_trend else None,
                      "project_id": ref.get("project_id"),
                      "source_aliases": ref.get("source_aliases", []),
                      "source_records": deepcopy(ref.get("source_records", [])),
                      "reference": deepcopy(ref)}
            if origin["source_kind"] == "unknown":
                warning = "存在来源类型未确认的已关联图片；保留 unknown，不推断文章或项目身份。"
                if warning not in warnings:
                    warnings.append(warning)
            try:
                path = self._path(result_id, ref, folder is None)
                digest = _sha(path)
                if ref.get("sha256") and ref["sha256"] != digest:
                    raise ValueError("原图 SHA 与登记记录不一致")
            except (OSError, ValueError, KeyError) as exc:
                missing.append({**origin, "reason": str(exc)})
                continue
            valid_references += 1
            origin["absolute_path"] = str(path)
            item = by_hash.setdefault(digest, {
                "image_id": digest, "sha256": digest, "path": str(path), "absolute_path": str(path),
                "preview_url": ref.get("preview_url") or ref.get("url") or ref.get("original_url"),
                "aliases": [], "source_record_ids": [], "direction_ids": [], "origins": [],
                "source_review": deepcopy(reviews.get(digest)), "_rejected": False})
            for field, value in (("aliases", ref.get("image_id")),
                                 ("source_record_ids", ref.get("source_record_id")),
                                 ("direction_ids", card["id"])):
                if value and value not in item[field]:
                    item[field].append(value)
            if origin not in item["origins"]:
                item["origins"].append(origin)
            item["_rejected"] |= _rejected(ref) or _rejected(reviews.get(digest, {}))
        images = []
        for item in by_hash.values():
            rejected = item.pop("_rejected")
            if rejected:
                excluded.append({**item, "reason": "保留已有人工排除／FAIL，未自动恢复入选"})
            else:
                images.append(item)
        if source_refs != self._source_refs(task, folder):
            raise ValueError("高潜结果或人工选图在读取期间发生变化，请重新预估")
        payload = {"result": self._metadata(task), "direction_ids": wanted,
                   "directions": [self._direction(card) for card in cards], "images": images,
                   "missing": missing, "excluded": excluded, "warnings": warnings,
                   "review_binding": review_binding, "source_refs": source_refs,
                   "counts": {"reference_count": references, "unique_images": len(images),
                              "missing": len(missing), "excluded": len(excluded),
                              "duplicate_references": valid_references - len(by_hash)}}
        payload["input_digest"] = _digest(payload)
        return payload

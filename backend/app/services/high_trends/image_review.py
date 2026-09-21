"""结果图片的独立副本、人工筛选和可追溯导出，不改原图或研究结论。"""

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from threading import RLock
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile

from PIL import Image, ImageOps


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
REVIEW_LOCK = RLock()
REMAINING_IMAGE_POLICY = "exclude_any_user_dislike_v1"
REMAINING_SCOPE = "扫描整个 data/trend_data 与 data/userreseach_data 目录，排除本次结果全部图片并按文件内容去重。排除任何用户标记 DISLIKE 的图片（含喜欢/不喜欢混合反馈），保留正向及未标注图片，默认未保留。"


def has_user_dislike(item):
    """合并来源后判断整张图；任一用户明确不喜欢即排除，不猜测未标注态度。"""
    for origin in item.get("origins", []):
        if origin.get("source_kind") != "user":
            continue
        tags = [origin.get("emotion_tag", "")]
        tags.extend(feedback.get("emotion_tag", "") for feedback in origin.get("feedback", []))
        if any("DISLIKE" in re.findall(r"[A-Z]+", str(tag).upper()) for tag in tags):
            return True
        if float(origin.get("dislike_count") or 0) > 0:
            return True
    return False


def filter_user_dislike(review):
    """仅其他图库使用：归档排除记录，保留其指纹和原选择，供后续比对。"""
    removed = [item for item in review["images"] if has_user_dislike(item)]
    removed_ids = {item["id"] for item in removed}
    review["images"] = [item for item in review["images"] if item["id"] not in removed_ids]
    review["excluded_user_dislike_images"] = removed
    review["excluded_user_dislike_sha256"] = [item["sha256"] for item in removed]
    review["user_image_policy"] = REMAINING_IMAGE_POLICY
    review["scope"] = REMAINING_SCOPE
    review["dedup_summary"].update(user_dislike_filtered_files=len(removed),
                                  remaining_unique_files=len(review["images"]))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def timestamp():
    return datetime.now(UTC).isoformat()


def write_atomic(path, value):
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def file_hash(path):
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class HighTrendImageReview:
    """以文件 SHA-256 合并相同字节，全部来源关系保留；选择状态按图片同步。"""

    def __init__(self, root, collection="result"):
        if collection not in {"result", "remaining"}:
            raise ValueError("未知图片集合")
        self.root = Path(root).resolve()
        self.output = self.root / "data/result/high_trend"
        self.collection = collection
        self.folder_name = "image_review" if collection == "result" else "image_review_remaining"
        self._lock = REVIEW_LOCK
        self._read_cache = {}

    def _read_review(self, folder):
        """图库有数千张时复用未变更的索引，避免每个图片请求重读整份来源 JSON。"""
        path = folder / "review.json"
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._read_cache.get(path)
        if cached is None or cached[0] != stamp:
            review = read(path)
            if self.collection == "remaining" and review.get("user_image_policy") != REMAINING_IMAGE_POLICY:
                # 旧图库升级也提升版本，阻止旧页面回写或复用含负向图的历史 ZIP。
                write_atomic(folder / f"review.before-dislike-filter.r{review['revision']}.json", review)
                filter_user_dislike(review)
                review.update(revision=review["revision"] + 1, updated_at=timestamp())
                review["history"].append({"revision": review["revision"], "time": review["updated_at"],
                                          "action": "exclude_user_dislike",
                                          "image_ids": review["excluded_user_dislike_sha256"]})
                write_atomic(path, review)
                stat = path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
            cached = (stamp, review)
            self._read_cache = {path: cached}
        return cached[1]

    def _run(self, task_id):
        if not re.fullmatch(r"web_[a-f0-9]{32}", task_id):
            raise FileNotFoundError("任务不存在")
        folder = self.output / task_id
        if not (folder / "web_task.json").is_file():
            raise FileNotFoundError("任务不存在")
        return folder

    def _source_path(self, value):
        path = Path(value) if value else None
        if path is None:
            return None
        path = (path if path.is_absolute() else self.root / path).resolve()
        roots = [self.root / "data/trend_data", self.root / "data/userreseach_data"]
        if (not any(path.is_relative_to(root.resolve()) for root in roots)
                or path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file()):
            return None
        return path

    def _url_index(self, inputs):
        """只补充原 JSON 已声明的图片 URL，不发网络请求或读取任意路径。"""
        index = {}

        def visit(value, parent):
            if isinstance(value, list):
                for child in value:
                    visit(child, parent)
            elif isinstance(value, dict):
                local = value.get("local_path")
                urls = [value[k] for k in ("url", "download_url", "resolved_url", "image_url")
                        if isinstance(value.get(k), str) and value[k].startswith(("https://", "http://"))]
                if isinstance(local, str) and local and urls:
                    path = Path(local)
                    key = str((path if path.is_absolute() else parent / path).resolve())
                    index.setdefault(key, set()).update(urls)
                for child in value.values():
                    if isinstance(child, (list, dict)):
                        visit(child, parent)

        for entry in inputs.values():
            path = Path(entry.get("path", ""))
            path = (path if path.is_absolute() else self.root / path).resolve()
            if (path.is_relative_to(self.root / "data") and path.suffix == ".json" and path.is_file()):
                visit(read(path), path.parent)
        return index

    @staticmethod
    def _counts(review):
        images = review["images"]
        retained = sum(item["retained"] for item in images)
        return {"total": len(images), "retained": retained, "excluded": len(images) - retained,
                "trend": sum("trend" in item["source_kinds"] for item in images),
                "user": sum("user" in item["source_kinds"] for item in images),
                "missing": len(review["missing"]), "reference_count": review["reference_count"]}

    def _public(self, review):
        # 完整排除来源留在本地索引；页面只需数量和指纹，避免传输大批不可选图片。
        result = deepcopy({key: value for key, value in review.items() if key != "excluded_user_dislike_images"})
        result["collection"] = self.collection
        result["counts"] = self._counts(review)
        for item in result["images"]:
            item["image_url"] = (f"/api/v1/high-trends/tasks/{review['task_id']}/image-review/"
                                 f"images/{item['id']}?collection={self.collection}")
        return result

    def _add_copy(self, staging, by_hash, by_path, path, origin, retained):
        """两个图库复用同一复制与去重规则，每个原路径及来源都可回查。"""
        key = str(path)
        if key not in by_path:
            by_path[key] = file_hash(path)
        digest = by_path[key]
        if digest not in by_hash:
            filename = digest + path.suffix.lower()
            copied = staging / "images" / filename
            shutil.copy2(path, copied)
            if file_hash(copied) != digest:
                raise RuntimeError("复制期间原图发生变化，请重试")
            width = height = None
            try:
                with Image.open(copied) as image:
                    width, height = image.size
            except (OSError, ValueError):
                pass
            by_hash[digest] = {"id": digest, "sha256": digest, "file_name": filename,
                               "copy_path": f"images/{filename}", "byte_size": copied.stat().st_size,
                               "width": width, "height": height, "retained": retained,
                               "source_kinds": [], "image_ids": [], "directions": [], "origins": []}
        item = by_hash[digest]
        if origin["source_kind"] not in item["source_kinds"]:
            item["source_kinds"].append(origin["source_kind"])
        if origin.get("image_id") and origin["image_id"] not in item["image_ids"]:
            item["image_ids"].append(origin["image_id"])
        if origin.get("direction_id"):
            direction = {"id": origin["direction_id"], "title": origin["direction_title"]}
            if direction not in item["directions"]:
                item["directions"].append(direction)
        if origin not in item["origins"]:
            item["origins"].append(origin)

    def create(self, task_id):
        """冻结当前结果引用并复制图片，重复进入不会重置选择或导入其他附件。"""
        with self._lock:
            run = self._run(task_id)
            destination = run / self.folder_name
            if (destination / "review.json").is_file():
                return self.get(task_id)
            if self.collection == "remaining":
                return self._create_remaining(task_id, run, destination)
            if read(run / "web_task.json").get("status") in {"queued", "running"}:
                raise RuntimeError("研究尚未结束，请在生成结果后整理图片")
            result_path = run / "high_potential_trends.json"
            result = read(result_path)
            sources = read(run / "sources.json")
            manifest = read(run / "manifest.json")
            inputs = manifest.get("inputs", {})
            url_index = self._url_index(inputs)
            cards = result.get("trends", []) + result.get("user_research_gaps", {}).get("directions", [])
            created = timestamp()
            review = {"schema_version": "high_trend_image_review.v1", "task_id": task_id,
                      "title": "高潜趋势 · 结果图片整理", "created_at": created, "updated_at": created,
                      "revision": 1, "folder": str(destination), "source_inputs": inputs,
                      "source_result_sha256": file_hash(result_path),
                      "source_result_file": str(result_path), "skill_version": manifest.get("skill_version"),
                      "model_profile": manifest.get("model_profile"),
                      "scope": "仅方向卡片引用的图片；不包含未关联方向的用户图片库存。",
                      "deduplication": "sha256_exact_bytes", "reference_count": 0,
                      "images": [], "missing": [], "history": []}
            by_hash, by_path = {}, {}
            with TemporaryDirectory(prefix=".image-review-", dir=run) as temporary:
                staging = Path(temporary) / "image_review"
                (staging / "images").mkdir(parents=True)
                for card in cards:
                    for ref in card.get("image_refs", []):
                        review["reference_count"] += 1
                        aliases = ref.get("evidence_ids", [])
                        matched = [(alias, sources[alias]) for alias in aliases if alias in sources]
                        if not matched:
                            matched = [(alias, src) for alias, src in sources.items()
                                       if src["id"] == ref.get("source_record_id")]
                        source = matched[0][1] if matched else {}
                        kind = "trend" if source.get("kind") == "trend" or ref.get("role") == "trend_reference" else "user"
                        raw_path = ref.get("absolute_path") or ref.get("path")
                        path = self._source_path(raw_path)
                        origin = {
                            "source_kind": kind, "image_id": ref.get("image_id"),
                            "source_record_id": ref.get("source_record_id"), "source_aliases": aliases,
                            "source_title": source.get("fields", {}).get("title_zh"),
                            "user_id": source.get("user_id"), "code": ref.get("code"),
                            "emotion_tag": ref.get("emotion_tag"), "original_path": ref.get("path"),
                            "original_absolute_path": str(path) if path else raw_path,
                            "source_file": inputs.get(source.get("source_file"), {}).get("path"),
                            "json_pointer": source.get("json_pointer"),
                            "source_records": [{"alias": alias, "record_id": src["id"],
                                                "json_pointer": src.get("json_pointer"),
                                                "user_id": src.get("user_id")} for alias, src in matched],
                            "urls": sorted(url_index.get(str(path), [])),
                            "direction_id": card["id"], "direction_title": card["title"],
                            "association_level": ref.get("association_level"),
                        }
                        if path is None:
                            review["missing"].append({**origin, "reason": "文件不存在、格式不支持或路径不在研究目录"})
                            continue
                        self._add_copy(staging, by_hash, by_path, path, origin, True)
                review["images"] = list(by_hash.values())
                write_atomic(staging / "review.json", review)
                (staging / "README.md").write_text(
                    "# 结果图片整理\n\nimages/ 保存按 SHA-256 去重的原图副本；review.json 保存全部来源、选择状态和操作记录。\n"
                    "网页排除图片只修改 retained，不删除副本或原始文件。exports/ 的文件是导出时的版本快照。\n"
                    "sha256 仅判断字节完全相同；缩放、裁切或重新压缩后的相似图片仍需另行比较。\n", encoding="utf-8")
                staging.replace(destination)
            return self._public(review)

    def _create_remaining(self, task_id, run, destination):
        """扫描整个两类资料目录，排除结果全集的指纹，不受人工保留/排除状态影响。"""
        from app.services.high_trends.image_inventory import scan_inventory

        baseline = HighTrendImageReview(self.root).create(task_id)
        excluded_hashes = {item["sha256"] for item in baseline["images"]}
        candidates, metadata_files, warnings = scan_inventory(self.root, IMAGE_SUFFIXES)
        created = timestamp()
        review = {"schema_version": "high_trend_image_review.v1", "collection": "remaining",
                  "task_id": task_id, "title": "其他图片 · 人工选图", "created_at": created,
                  "updated_at": created, "revision": 1, "folder": str(destination),
                  "source_inputs": baseline.get("source_inputs", {}),
                  "source_result_sha256": baseline["source_result_sha256"],
                  "source_result_file": baseline["source_result_file"],
                  "scope": REMAINING_SCOPE,
                  "scan_roots": [str(self.root / "data/trend_data"), str(self.root / "data/userreseach_data")],
                  "metadata_files": metadata_files, "warnings": warnings,
                  "deduplication": "sha256_exact_bytes", "reference_count": len(candidates),
                  "excluded_result_sha256": sorted(excluded_hashes), "excluded_result_files": [],
                  "images": [], "missing": [], "history": []}
        by_hash, by_path, candidate_hashes, excluded_found = {}, {}, set(), set()
        with TemporaryDirectory(prefix=".image-review-", dir=run) as temporary:
            staging = Path(temporary) / self.folder_name
            (staging / "images").mkdir(parents=True)
            for raw_path, origins in candidates.items():
                path = self._source_path(raw_path)
                if path is None:
                    review["missing"].append({"original_absolute_path": raw_path, "reason": "扫描后文件消失或路径不可用"})
                    continue
                digest = file_hash(path)
                candidate_hashes.add(digest)
                by_path[str(path)] = digest
                if digest in excluded_hashes:
                    excluded_found.add(digest)
                    review["excluded_result_files"].append({"original_absolute_path": str(path), "sha256": digest})
                    continue
                for origin in origins:
                    self._add_copy(staging, by_hash, by_path, path, origin, False)
            review["images"] = list(by_hash.values())
            review["dedup_summary"] = {"scanned_files": len(candidates),
                                       "candidate_unique_files": len(candidate_hashes),
                                       "excluded_result_files": len(excluded_found),
                                       "remaining_unique_files": len(by_hash)}
            filter_user_dislike(review)
            write_atomic(staging / "review.json", review)
            (staging / "README.md").write_text(
                "# 其他图片选图\n\n两个研究目录全量扫描，按 SHA-256 排除结果图库全部图片，再去重复制。\n"
                "任一用户标记 DISLIKE 的图片不进入可选图库，混合反馈也排除；未标注图片不推断喜欢，默认 retained=false。\n"
                "被过滤图片的来源及指纹归档于 review.json 的 excluded_user_dislike_images，不删除原文件。\n"
                "review.json 保留来源关系、原路径、情绪标记、文件指纹、去重统计和选择记录。\n"
                "图库独立于结果图库；排除操作不删除原图，导出时只打包已保留图片。\n", encoding="utf-8")
            staging.replace(destination)
        return self._public(review)

    def get(self, task_id):
        with self._lock:
            return self._public(self._read_review(self._run(task_id) / self.folder_name))

    def update(self, task_id, revision, image_ids, retained):
        """先核对整批与版本再原子保存，旧页面不能覆盖其他页面的新选择。"""
        with self._lock:
            folder = self._run(task_id) / self.folder_name
            path = folder / "review.json"
            review = deepcopy(self._read_review(folder))
            if review["revision"] != revision:
                raise RuntimeError("图片选择已在其他页面更新，请刷新后重试")
            wanted = set(image_ids)
            if not wanted or not wanted.issubset({item["id"] for item in review["images"]}):
                raise ValueError("图片编号不存在或没有选择图片")
            changed = [item for item in review["images"] if item["id"] in wanted and item["retained"] != retained]
            if changed:
                updated = timestamp()
                for item in changed:
                    item.update(retained=retained, selection_updated_at=updated)
                review.update(revision=revision + 1, updated_at=updated)
                review["history"].append({"revision": review["revision"], "time": updated,
                                          "retained": retained, "image_ids": [item["id"] for item in changed]})
                write_atomic(path, review)
            return self._public(review)

    def _copied_path(self, folder, item):
        path = (folder / item["copy_path"]).resolve()
        if (not path.is_relative_to((folder / "images").resolve())
                or path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file()):
            raise FileNotFoundError("图片副本不存在")
        return path

    def image(self, task_id, image_id, thumbnail=False):
        with self._lock:
            folder = self._run(task_id) / self.folder_name
            review = self._read_review(folder)
            item = next((item for item in review["images"] if item["id"] == image_id), None)
            if item is None:
                raise FileNotFoundError("图片不在本次整理中")
            path = self._copied_path(folder, item)
            if not thumbnail:
                return path
            # 网格只加载小预览，点击大图与导出仍使用原始副本；JPEG draft 避免解码超大原图。
            target = folder / "thumbnails" / f"{image_id}.webp"
            if not target.is_file():
                target.parent.mkdir(exist_ok=True)
                temporary = target.with_name(f".{image_id}.{uuid4().hex}.tmp")
                try:
                    with Image.open(path) as image:
                        image.draft("RGB", (640, 640))
                        image.thumbnail((640, 640))
                        preview = ImageOps.exif_transpose(image)
                        if preview.mode not in {"RGB", "RGBA"}:
                            preview = preview.convert("RGBA")
                        preview.save(temporary, format="WEBP", quality=85)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            return target

    def download(self, task_id, format):
        """导出带版本号的保留图快照；完整索引另存以便与未入选图片比较。"""
        with self._lock:
            folder = self._run(task_id) / self.folder_name
            review = self._read_review(folder)
            selected = {key: value for key, value in review.items()
                        if key not in {"images", "history", "excluded_user_dislike_images"}}
            selected.update(images=[item for item in review["images"] if item["retained"]],
                            counts=self._counts(review),
                            all_collection_sha256=[item["sha256"] for item in review["images"]],
                            all_result_sha256=(review.get("excluded_result_sha256") if self.collection == "remaining"
                                               else [item["sha256"] for item in review["images"]]),
                            excluded_sha256=[item["sha256"] for item in review["images"] if not item["retained"]])
            export = folder / "exports"
            export.mkdir(exist_ok=True)
            stem = f"retained-r{review['revision']}"
            if format == "json":
                path = export / f"{stem}.json"
                write_atomic(path, selected)
                return path
            if format != "zip":
                raise ValueError("不支持的导出格式")
            path = export / f"{stem}.zip"
            if path.is_file():
                return path
            temporary = export / f".{stem}.{uuid4().hex}.tmp"
            try:
                with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
                    for item in selected["images"]:
                        copied = self._copied_path(folder, item)
                        if file_hash(copied) != item["sha256"]:
                            raise RuntimeError("图片副本内容已改变，未导出，请检查文件")
                        archive.write(copied, item["copy_path"])
                    archive.writestr("selection.json", json.dumps(selected, ensure_ascii=False, indent=2))
                    archive.writestr("review.json", json.dumps(review, ensure_ascii=False, indent=2))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            return path

"""少量微型图片验证副本隔离、来源保留、选择冲突及导出，不调用模型。"""

import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from PIL import Image
from app.services.high_trends.image_review import HighTrendImageReview, has_user_dislike, read, write_atomic


class ImageReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.task = "web_" + "a" * 32
        self.run = self.root / "data/result/high_trend" / self.task
        self.run.mkdir(parents=True)
        self.trend = self.root / "data/trend_data/a.png"
        self.trend.parent.mkdir(parents=True)
        Image.new("RGB", (3, 2), "red").save(self.trend)
        self.user = self.root / "data/userreseach_data/duplicate.png"
        self.user.parent.mkdir(parents=True)
        self.user.write_bytes(self.trend.read_bytes())
        self.other = self.user.with_name("other.png")
        Image.new("RGB", (2, 2), "blue").save(self.other)
        self.original = self.trend.read_bytes()
        sources = {
            "T1": {"id": "trend:1", "kind": "trend", "source_file": "trends",
                   "fields": {"title_zh": "趋势原文"}, "json_pointer": "/trends/0"},
            "U1": {"id": "user:1:qa:1", "kind": "user_qa", "user_id": "1",
                   "source_file": "users", "json_pointer": "/users/0/aesthetic_research/0"},
        }
        def ref(path, alias, image_id):
            return {"absolute_path": str(path), "path": str(path), "image_id": image_id,
                    "source_record_id": sources[alias]["id"], "evidence_ids": [alias],
                    "role": "trend_reference" if alias == "T1" else "user_unclear"}
        self.refs = [ref(self.trend, "T1", "t1"), ref(self.user, "U1", "u1"),
                     ref(self.other, "U1", "u2"), ref(self.user.with_name("missing.png"), "U1", "u3")]
        for name, value in {
            "web_task": {"status": "completed"}, "manifest": {"inputs": {}}, "sources": sources,
            "high_potential_trends": {"trends": [{"id": "D1", "title": "方向", "image_refs": self.refs}],
                                      "user_research_gaps": {"directions": []},
                                      "user_images": [{"path": "/not-in-result.png"}]},
        }.items():
            write_atomic(self.run / f"{name}.json", value)
        self.service = HighTrendImageReview(self.root)

    def test_exact_duplicates_keep_both_origins_and_only_card_scope(self):
        review = self.service.create(self.task)
        self.assertEqual(review["counts"], {"total": 2, "retained": 2, "excluded": 0,
                                          "trend": 1, "user": 2, "missing": 1, "reference_count": 4})
        shared = review["images"][0]
        self.assertEqual(shared["source_kinds"], ["trend", "user"])
        self.assertEqual(shared["image_ids"], ["t1", "u1"])
        self.assertEqual(len(shared["origins"]), 2)
        self.assertEqual((shared["width"], shared["height"]), (3, 2))
        self.assertEqual(self.service.image(self.task, shared["id"]).read_bytes(), self.original)
        self.assertEqual(len(list((self.run / "image_review/images").iterdir())), 2)

    def test_selection_survives_reentry_and_export_keeps_only_retained_files(self):
        review = self.service.create(self.task)
        excluded = review["images"][0]["id"]
        saved = self.service.update(self.task, 1, [excluded], False)
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(self.service.create(self.task)["counts"]["retained"], 1)
        self.assertTrue(self.service.image(self.task, excluded).is_file())
        self.assertEqual(self.trend.read_bytes(), self.original)
        export = read(self.service.download(self.task, "json"))
        self.assertEqual(len(export["images"]), 1)
        self.assertEqual(export["excluded_sha256"], [excluded])
        self.assertEqual(len(export["all_result_sha256"]), 2)
        with ZipFile(self.service.download(self.task, "zip")) as archive:
            files = [name for name in archive.namelist() if name.startswith("images/")]
            self.assertEqual(files, [export["images"][0]["copy_path"]])
            self.assertEqual(len(json.loads(archive.read("review.json"))["images"]), 2)
        self.assertEqual(self.service.update(self.task, 2, [excluded], True)["counts"]["retained"], 2)

    def test_stale_version_and_unknown_batch_do_not_change_selection(self):
        review = self.service.create(self.task)
        image_id = review["images"][0]["id"]
        with self.assertRaises(ValueError):
            self.service.update(self.task, 1, [image_id, "unknown"], False)
        self.assertEqual(self.service.get(self.task)["counts"]["retained"], 2)
        self.service.update(self.task, 1, [image_id], False)
        with self.assertRaises(RuntimeError):
            self.service.update(self.task, 1, [image_id], True)
        self.assertEqual(self.service.get(self.task)["counts"]["retained"], 1)

    def test_unsafe_source_and_download_ids_are_rejected(self):
        outside = self.root / "private.png"
        outside.write_bytes(self.original)
        linked = self.user.with_name("escape.png")
        linked.symlink_to(outside)
        path = self.run / "high_potential_trends.json"
        value = read(path)
        value["trends"][0]["image_refs"].append({**self.refs[0], "absolute_path": str(linked)})
        write_atomic(path, value)
        self.assertEqual(self.service.create(self.task)["counts"]["missing"], 2)
        with self.assertRaises(FileNotFoundError):
            self.service.image(self.task, "../../private.png")
        with self.assertRaises(FileNotFoundError):
            self.service.create("../../private")

    def test_export_refuses_changed_copy(self):
        review = self.service.create(self.task)
        copied = self.service.image(self.task, review["images"][0]["id"])
        copied.write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "副本内容已改变"):
            self.service.download(self.task, "zip")
        self.assertEqual(self.trend.read_bytes(), self.original)

    def test_thumbnail_is_separate_from_original_and_export(self):
        review = self.service.create(self.task)
        item = review["images"][0]
        thumbnail = self.service.image(self.task, item["id"], thumbnail=True)
        self.assertEqual(thumbnail.suffix, ".webp")
        with Image.open(thumbnail) as image:
            self.assertLessEqual(max(image.size), 640)
        self.assertEqual(self.service.image(self.task, item["id"]).read_bytes(), self.original)
        with ZipFile(self.service.download(self.task, "zip")) as archive:
            self.assertFalse(any("thumbnails/" in name for name in archive.namelist()))

    def test_remaining_scans_full_directories_and_excludes_all_result_hashes(self):
        initial = self.service.create(self.task)
        self.service.update(self.task, 1, [initial["images"][0]["id"]], False)
        source_snapshot = (self.run / "image_review/review.json").read_bytes()
        added = self.trend.with_name("unreferenced.png")
        Image.new("RGB", (4, 2), "green").save(added)
        duplicate = self.user.with_name("same-green.png")
        duplicate.write_bytes(added.read_bytes())
        manifest = self.user.parent / "images.json"
        write_atomic(manifest, {"images": [{"id": "u-extra", "local_path": duplicate.name,
                                           "emotion_tag": ["ENJOY"], "reference_codes": ["P9"],
                                           "responses": [{"user_id": "3", "emotion_tag": "ENJOY"}]}]})
        remaining = HighTrendImageReview(self.root, "remaining")
        review = remaining.create(self.task)
        self.assertEqual(review["counts"]["total"], 1)
        self.assertEqual(review["counts"]["retained"], 0)
        self.assertEqual(set(review["images"][0]["source_kinds"]), {"trend", "user"})
        self.assertEqual(review["dedup_summary"], {"scanned_files": 5, "candidate_unique_files": 3,
                                                  "excluded_result_files": 2, "remaining_unique_files": 1,
                                                  "user_dislike_filtered_files": 0})
        origin = next(o for o in review["images"][0]["origins"] if o["source_kind"] == "user")
        self.assertEqual(origin["emotion_tag"], "ENJOY")
        self.assertEqual(origin["code"], "P9")
        self.assertEqual(origin["feedback"][0]["user_id"], "3")
        self.assertIn("collection=remaining", review["images"][0]["image_url"])
        remaining.update(self.task, 1, [review["images"][0]["id"]], True)
        self.assertEqual(remaining.create(self.task)["counts"]["retained"], 1)
        self.assertEqual((self.run / "image_review/review.json").read_bytes(), source_snapshot)
        export = read(remaining.download(self.task, "json"))
        self.assertEqual(len(export["all_result_sha256"]), 2)
        self.assertEqual(len(export["all_collection_sha256"]), 1)

    def test_remaining_keeps_unindexed_files_when_metadata_is_invalid(self):
        added = self.user.with_name("unindexed.png")
        Image.new("RGB", (2, 3), "yellow").save(added)
        (self.user.parent / "users.json").write_text('{"users": [invalid]}')
        review = HighTrendImageReview(self.root, "remaining").create(self.task)
        self.assertEqual(review["counts"]["total"], 1)
        self.assertEqual(len(review["warnings"]), 1)
        self.assertEqual(review["images"][0]["origins"][0]["association_level"], "directory_inventory")
        self.assertIsNone(review["images"][0]["origins"][0]["emotion_tag"])

    def test_dislike_detection_accepts_mixed_and_aggregated_user_feedback(self):
        for fields in ({"emotion_tag": "ENJOY / dislike"}, {"emotion_tag": ["LIKE", "DISLIKE"]},
                       {"feedback": [{"emotion_tag": "DISLIKE"}]}, {"dislike_count": 1}):
            with self.subTest(fields=fields):
                self.assertTrue(has_user_dislike({"origins": [{"source_kind": "user", **fields}]}))
                self.assertFalse(has_user_dislike({"origins": [{"source_kind": "trend", **fields}]}))
        self.assertFalse(has_user_dislike({"origins": [{"source_kind": "user", "emotion_tag": "LIKE"}]}))

    def test_remaining_filters_new_gallery_and_migrates_old_selection_once(self):
        self.service.create(self.task)
        result_before = (self.run / "image_review/review.json").read_bytes()
        for name, color in (("negative.png", "green"), ("positive.png", "yellow")):
            Image.new("RGB", (4, 3), color).save(self.user.with_name(name))
        write_atomic(self.user.parent / "images.json", {"images": [
            {"id": "negative", "local_path": "negative.png", "emotion_tag": ["ENJOY", "DISLIKE"]},
            {"id": "positive", "local_path": "positive.png", "emotion_tag": "LIKE"},
        ]})
        service = HighTrendImageReview(self.root, "remaining")
        review = service.create(self.task)
        self.assertEqual(review["counts"]["total"], 1)
        self.assertEqual(review["dedup_summary"]["user_dislike_filtered_files"], 1)
        self.assertNotIn("excluded_user_dislike_images", review)
        path = self.run / "image_review_remaining/review.json"
        legacy = read(path)
        removed = legacy.pop("excluded_user_dislike_images")
        legacy.pop("excluded_user_dislike_sha256")
        legacy.pop("user_image_policy")
        legacy["images"].extend(removed)
        for item in legacy["images"]:
            item["retained"] = True
        legacy["revision"] = 7
        write_atomic(path, legacy)
        with self.assertRaises(RuntimeError):
            service.update(self.task, 7, [removed[0]["id"]], True)
        migrated = service.get(self.task)
        self.assertEqual(migrated["revision"], 8)
        self.assertEqual(migrated["counts"]["retained"], 1)
        self.assertEqual(read(path)["excluded_user_dislike_images"], removed)
        self.assertEqual(read(path.with_name("review.before-dislike-filter.r7.json")), legacy)
        self.assertEqual(service.create(self.task)["revision"], 8)
        with self.assertRaises(FileNotFoundError):
            service.image(self.task, removed[0]["id"])
        exported = read(service.download(self.task, "json"))
        self.assertEqual(exported["excluded_user_dislike_sha256"], [removed[0]["sha256"]])
        self.assertEqual(len(exported["images"]), 1)
        with ZipFile(service.download(self.task, "zip")) as archive:
            self.assertNotIn(removed[0]["copy_path"], archive.namelist())
        self.assertEqual((self.run / "image_review/review.json").read_bytes(), result_before)


if __name__ == "__main__":
    unittest.main()

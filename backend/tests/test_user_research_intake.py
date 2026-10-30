"""用研模型回复的来源约束与任务生命周期；不调用真实模型或原始五用户资料。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile

from app.agents.user_research_intake import validate_result
from app.services.user_research import tasks as task_module
from app.services.user_research.storage import ResearchStore


def slide_fixture(number: int = 1) -> dict:
    """四个文字形状分别覆盖问题、回答、画像和主持人提示。"""
    return {
        "number": number,
        "texts": [
            {"shapePath": "/0", "text": "哪些图片喜欢或不喜欢？"},
            {"shapePath": "/1", "text": "喜欢 P1；不喜欢 P2；喜欢 P9，但图片缺失。"},
            {"shapePath": "/2", "text": "职业：学生"},
            {"shapePath": "/3", "text": "主持人提示：继续追问原因。"},
        ],
        "notes": ["主持人提示，不作为本人回答。"],
        "pictures": [
            {"id": f"pic-{number}-1", "shapePath": "/4"},
            {"id": f"pic-{number}-2", "shapePath": "/5"},
        ],
    }


def result_fixture(number: int = 1) -> dict:
    choices = []
    for index, emotion in ((1, "ENJOY"), (2, "DISLIKE"), (9, "ENJOY")):
        choices.append({
            "pictureId": f"pic-{number}-{index}" if index != 9 else None,
            "code": f"P{index}", "emotion": emotion, "description": "",
            "evidenceScope": "exact" if index != 9 else "missing_source_image",
            "evidenceKind": "text", "evidenceText": f"{'不喜欢' if index == 2 else '喜欢'} P{index}",
        })
    return {
        "records": [{
            "section": "外观偏好", "question": "哪些图片喜欢或不喜欢？",
            "answer": "喜欢 P1；不喜欢 P2；喜欢 P9，但图片缺失。",
            "originalAnswer": "喜欢 P1；不喜欢 P2；喜欢 P9，但图片缺失。",
            "role": "respondent_answer", "answerShapePaths": ["/1"], "images": choices,
        }],
        "profile": [{"key": "profession", "value": "学生", "sourceShapePaths": ["/2"]}],
        "skipped": [
            {"shapePath": "/0", "role": "template_question", "reason": "题干，回答另见 /1。"},
            {"shapePath": "/3", "role": "interviewer_prompt", "reason": "主持人提示不作为用户回答。"},
        ],
        "warnings": ["P9 原图缺失，保留明确选择。"],
    }


class IntakeResultTests(unittest.TestCase):
    def validate(self, value: dict):
        return validate_result(json.dumps(value, ensure_ascii=False), slide_fixture())

    def test_accepts_complete_shape_routes_and_keeps_missing_image_attitude(self):
        result = self.validate(result_fixture())
        self.assertEqual(result.records[0].answerShapePaths, ["/1"])
        self.assertEqual(result.profile[0].sourceShapePaths, ["/2"])
        self.assertIsNone(result.records[0].images[2].pictureId)
        self.assertEqual(result.records[0].images[2].emotion, "ENJOY")
        self.assertEqual(result.records[0].images[2].evidenceScope, "missing_source_image")

    def test_rejects_omitted_and_unknown_text_shape_in_each_route(self):
        mutations = [
            lambda value: value["skipped"].pop(),
            lambda value: value["records"][0]["answerShapePaths"].append("/unknown-answer"),
            lambda value: value["profile"][0]["sourceShapePaths"].append("/unknown-profile"),
            lambda value: value["skipped"].append({"shapePath": "/unknown-skip", "role": "other", "reason": "未知"}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(route=index):
                value = result_fixture()
                mutate(value)
                with self.assertRaisesRegex(ValueError, "文本覆盖不完整或含未知形状"):
                    self.validate(value)

    def test_rejects_unknown_picture_bad_scope_and_unsupported_emotion(self):
        changes = [
            {"pictureId": "picture-from-another-page"},
            {"pictureId": None, "evidenceScope": "exact"},
            {"evidenceScope": "missing_source_image"},
            {"emotion": "LIKE"},
            {"emotion": "ENJOY", "evidenceKind": "user_inserted_reference"},
            {"evidenceText": "源文件里不存在的喜欢理由"},
        ]
        for change in changes:
            with self.subTest(change=change):
                value = result_fixture()
                value["records"][0]["images"][0].update(change)
                with self.assertRaises(ValueError):
                    self.validate(value)

    def test_rejects_answer_without_evidence_and_unexpected_fields(self):
        value = result_fixture()
        value["records"][0].update(answerShapePaths=[], images=[])
        with self.assertRaisesRegex(ValueError, "回答缺少文本或图片来源"):
            self.validate(value)
        value = result_fixture()
        value["modelMayIgnoreSource"] = True
        with self.assertRaises(ValueError):
            self.validate(value)


class ResearchTaskLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = ResearchStore(root=self.root / "runs", seed_file=self.root / "missing-seed.json", image_root=self.root / "images")
        self.manager = task_module.ResearchTasks(self.store)
        self.payload = b"synthetic fixture: actual PPT ZIP is covered by presentation tests"
        self.model_patch = patch.object(task_module, "get_model", return_value={"id": "fake-model"})
        self.model_patch.start()
        self.addCleanup(self.model_patch.stop)

    async def create(self, payload: bytes | None = None, filename: str = "虚构调研.pptx") -> dict:
        upload = UploadFile(file=io.BytesIO(self.payload if payload is None else payload), filename=filename)
        return await self.manager.create(upload, "  虚构用户  ", "fake-model")

    def prepare(self, source: Path, run: Path) -> dict:
        """替代 ZIP/Office 阶段，仅为存储准备受控的小文件。"""
        run.mkdir(parents=True)
        media = run / "media"
        media.mkdir()
        slide = slide_fixture()
        for picture in slide["pictures"]:
            path = media / f"{picture['id']}.png"
            path.write_bytes(b"synthetic original image bytes")
            picture["localPath"] = str(path)
        render = run / "page-001.jpg"
        render.write_bytes(b"synthetic page render")
        slide["renderPath"] = str(render)
        return {"sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(), "slideCount": 1, "slides": [slide]}

    async def extract(self, slide: dict, **_options):
        return validate_result(json.dumps(result_fixture(slide["number"]), ensure_ascii=False), slide)

    async def test_upload_duplicate_run_review_confirm_and_completed_idempotency(self):
        first = await self.create(filename="../../虚构调研.pptx")
        self.assertEqual(first["filename"], "虚构调研.pptx")
        self.assertEqual(first["name"], "虚构用户")
        self.assertEqual(first["status"], "queued")
        self.assertEqual((self.store._run(first["id"]) / "input.pptx").read_bytes(), self.payload)
        duplicate = await self.create()
        self.assertEqual(duplicate["id"], first["id"])
        self.assertEqual(len(self.store.list_tasks()), 1)
        self.assertEqual(len(list(self.store.root.iterdir())), 1)
        with self.assertRaisesRegex(ValueError, "待核对"):
            self.manager.confirm(first["id"])
        with patch.object(task_module, "prepare_presentation", side_effect=self.prepare) as prepare, patch.object(task_module, "extract_slide", new_callable=AsyncMock, side_effect=self.extract) as extract, patch.object(task_module, "frozen_prompt", return_value="synthetic prompt"):
            await self.manager.run(first["id"])
            await self.manager.run(first["id"])
        prepare.assert_called_once()
        extract.assert_awaited_once()
        task = self.store.get_task(first["id"])
        self.assertEqual((task["status"], task["processedSlides"], task["totalSlides"]), ("needs_review", 1, 1))
        user = self.store.get_user(first["userId"])
        self.assertEqual(user["status"], "needs_review")
        self.assertEqual(user["profile"], {"profession": "学生"})
        self.assertEqual((user["recordCount"], user["enjoyCount"], user["dislikeCount"], user["missingImageCount"]), (1, 2, 1, 1))
        self.assertEqual(user["records"][0]["sourceShapePaths"], ["/1"])
        self.assertEqual(user["images"][2]["emotion"], "ENJOY")
        self.assertIsNone(user["images"][2]["url"])
        self.assertEqual(self.store.asset_path(user["id"], user["images"][0]["id"]).read_bytes(), b"synthetic original image bytes")
        self.assertEqual(user["provenance"]["promptSha256"], hashlib.sha256(b"synthetic prompt").hexdigest())
        completed = self.manager.confirm(first["id"])
        self.assertEqual(completed["status"], "completed")
        confirmed = self.store.get_user(user["id"])
        self.assertEqual(confirmed["status"], "ready")
        self.assertIn("confirmedAt", confirmed["provenance"])
        self.assertEqual(self.manager.confirm(first["id"]), completed)
        self.assertEqual((await self.create())["id"], first["id"])
        self.assertEqual(len(self.store.list_users()), 1)

    async def test_midway_failure_keeps_progress_but_publishes_no_user(self):
        task = await self.create()

        def two_pages(source, run):
            inventory = self.prepare(source, run)
            second = deepcopy(inventory["slides"][0])
            second["number"] = 2
            inventory["slides"].append(second)
            inventory["slideCount"] = 2
            return inventory

        calls = 0

        async def fail_after_first(slide, **options):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("provider response contains secret=do-not-publish")
            return await self.extract(slide, **options)

        with patch.object(task_module, "prepare_presentation", side_effect=two_pages), patch.object(task_module, "extract_slide", side_effect=fail_after_first), patch.object(task_module, "frozen_prompt", return_value="synthetic prompt"):
            await self.manager.run(task["id"])
        failed = self.store.get_task(task["id"])
        self.assertEqual((failed["status"], failed["processedSlides"]), ("failed", 1))
        self.assertNotIn("do-not-publish", json.dumps(failed))
        self.assertTrue((self.store._run(task["id"]) / "failure.json").is_file())
        self.assertFalse((self.store._run(task["id"]) / "user.json").exists())
        self.assertEqual(self.store.list_users(), [])
        with self.assertRaises(ValueError):
            self.manager.confirm(task["id"])
        self.assertNotEqual((await self.create())["id"], task["id"])

    async def test_preparation_failure_does_not_call_model_or_publish_result(self):
        task = await self.create()
        with patch.object(task_module, "prepare_presentation", side_effect=ValueError("PPTX 含外部链接")), patch.object(task_module, "extract_slide", new_callable=AsyncMock) as extract:
            await self.manager.run(task["id"])
        extract.assert_not_awaited()
        self.assertEqual(self.store.get_task(task["id"])["status"], "failed")
        self.assertEqual(self.store.list_users(), [])

    async def test_recover_marks_interrupted_tasks_without_replaying_models(self):
        queued = await self.create()
        extracting = await self.create(payload=self.payload + b"another")
        self.manager.update(extracting, status="extracting", processedSlides=1)
        review = await self.create(payload=self.payload + b"review")
        self.manager.update(review, status="needs_review")
        with patch.object(task_module, "prepare_presentation") as prepare, patch.object(task_module, "extract_slide", new_callable=AsyncMock) as extract:
            self.manager.recover()
            await self.manager.run(queued["id"])
            await self.manager.run(extracting["id"])
            self.manager.recover()
        prepare.assert_not_called()
        extract.assert_not_awaited()
        for original in (queued, extracting):
            recovered = self.store.get_task(original["id"])
            self.assertEqual((recovered["status"], recovered["stage"]), ("failed", "interrupted"))
        self.assertEqual(self.store.get_task(extracting["id"])["processedSlides"], 1)
        self.assertEqual(self.store.get_task(review["id"])["status"], "needs_review")

    async def test_invalid_or_oversize_upload_does_not_leave_a_task(self):
        with self.assertRaisesRegex(ValueError, "pptx"):
            await self.create(filename="fixture.ppt")
        with self.assertRaisesRegex(ValueError, "为空"):
            await self.create(payload=b"")
        with patch.object(task_module, "MAX_COMPRESSED_BYTES", 4):
            with self.assertRaisesRegex(ValueError, "100 MB"):
                await self.create(payload=b"too large")
        self.assertEqual(self.store.list_tasks(), [])
        self.assertEqual(list(self.store.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

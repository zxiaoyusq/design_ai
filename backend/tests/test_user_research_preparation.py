"""用户调研整理的用户隔离、关系去重、图片计票和下载归属验证。"""

import hashlib
import io
import json
import re
import tempfile
import threading
import unittest
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.prepare_user_research_data import (
    PROFILE_FIELDS,
    build_records,
    download_research_image,
    fetch_source,
    fetch_user_names,
    main,
    merge_user_names,
)
from tests.test_trend_data_preparation import make_png


EXPECTED_PROFILE_FIELDS = (
    "country", "profession", "age", "using_mobile_phone_prices",
    "using_mobile_phone_brand", "academic_qualification", "purchase_drivers",
    "user_group_tags", "gender", "mobile_function_usage_preferences",
)


def snapshot(**tables: list[dict]) -> dict:
    """补齐六份查询结果，测试不接触真实数据库。"""
    return {
        table: tables.get(table, [])
        for table in (
            "users", "aesthetic_research", "demands", "image_responses",
            "aesthetic_links", "demand_links",
        )
    }


def user(identifier: int, **fields: object) -> dict:
    return {"id": identifier, "bid": f"user-{identifier}", "delete_flag": 0, **fields}


def question(identifier: int, **fields: object) -> dict:
    return {
        "id": identifier, "bid": f"question-{identifier}", "delete_flag": 0,
        "answer_type": "开放回答", "scenario_type": "通勤", "question_type": "外观偏好",
        "question": f"第 {identifier} 个问题", "ai_analysis": "保留原分析。", **fields,
    }


def demand(identifier: int, **fields: object) -> dict:
    return {
        "id": identifier, "bid": f"demand-{identifier}", "delete_flag": 0,
        "ai_index": '{"便携":0.9}', "scenario": "户外", "ref_pic": '[]', **fields,
    }


def link(identifier: int, user_id: int, target: str, **fields: object) -> dict:
    return {
        "id": identifier, "source_bid": f"user-{user_id}", "target_bid": target,
        "delete_flag": 0, **fields,
    }


def response(identifier: int, user_id: int, url: object, emotion: object = "ENJOY", **fields: object) -> dict:
    return {
        "id": identifier, "bid": f"response-{identifier}", "delete_flag": 0,
        "id_user_bid": f"user-{user_id}", "url": url, "emotion_tag": emotion,
        "survey_pic_bid": "survey-picture-1", "name": "P20", **fields,
    }


class UserResearchRecordsTestCase(unittest.TestCase):
    def test_unmentioned_analysis_excludes_whole_question_without_creating_orphans(self) -> None:
        source = snapshot(
            users=[user(1), user(2)],
            aesthetic_research=[
                question(11, ai_analysis="用户未提及颜色偏好"),
                question(12, ai_analysis="喜欢蓝色，但未提及材质"),
                question(13, ai_analysis=json.dumps({"结论": "未提及"})),
                question(14, question="是否有未提及的需求？", ai_analysis="喜欢曲线"),
                question(15, ai_analysis="未提及", delete_flag=1),
            ],
            aesthetic_links=[link(101, 1, "question-11"), link(102, 2, "question-11"),
                             link(103, 1, "question-12"), link(104, 1, "question-14")],
            demands=[demand(21, ai_index="未提及")],
            demand_links=[link(201, 1, "demand-21")],
        )
        users, _, diagnostics = build_records(source)
        self.assertEqual([entry["id"] for entry in users[0]["aesthetic_research"]], ["14"])
        self.assertEqual(users[1]["aesthetic_research"], [])
        self.assertEqual(diagnostics["unlinked_aesthetic_research"], [])
        self.assertEqual(diagnostics["excluded_unmentioned_aesthetic_research_count"], 3)
        self.assertEqual(diagnostics["ignored_relation_count"], 0)
        self.assertEqual(users[0]["demand_research"][0]["ai_index"], "未提及")
        self.assertEqual(len(source["aesthetic_research"]), 5)

    def test_profile_and_research_fields_preserve_structured_json_and_plain_text(self) -> None:
        source = snapshot(
            users=[user(
                1, name="李小明", country="中国", profession='["设计师", "研究员"]', age=32,
                using_mobile_phone_prices="4000–6000元", using_mobile_phone_brand="A，B",
                academic_qualification="本科", purchase_drivers='{"外观":true}',
                user_group_tags='["设计敏感"]', gender="女",
                mobile_function_usage_preferences="摄影，导航；阅读",
            )],
            aesthetic_research=[question(11, ai_analysis='{"判断":"偏好曲线"}')],
            demands=[demand(21, ref_pic='[{"url":"https://example.test/ref.png"}]')],
            aesthetic_links=[link(101, 1, "question-11")],
            demand_links=[link(201, 1, "demand-21")],
        )

        users, images, diagnostics = build_records(source)

        self.assertEqual(tuple(PROFILE_FIELDS), EXPECTED_PROFILE_FIELDS)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["id"], "1")
        self.assertEqual(users[0]["bid"], "user-1")
        self.assertEqual(users[0]["name"], "李小明")
        profile = users[0]["profile"]
        self.assertEqual(set(profile), set(EXPECTED_PROFILE_FIELDS))
        self.assertEqual(profile["profession"], ["设计师", "研究员"])
        self.assertEqual(profile["purchase_drivers"], {"外观": True})
        self.assertEqual(profile["user_group_tags"], ["设计敏感"])
        self.assertEqual(profile["mobile_function_usage_preferences"], "摄影，导航；阅读")
        self.assertEqual(profile["using_mobile_phone_brand"], "A，B")
        self.assertEqual(profile["age"], 32)
        qa = users[0]["aesthetic_research"][0]
        self.assertEqual((qa["id"], qa["bid"]), ("11", "question-11"))
        for field in ("answer_type", "scenario_type", "question_type", "question"):
            self.assertEqual(qa[field], source["aesthetic_research"][0][field])
        self.assertEqual(qa["ai_analysis"], {"判断": "偏好曲线"})
        needs = users[0]["demand_research"][0]
        self.assertEqual((needs["id"], needs["bid"]), ("21", "demand-21"))
        self.assertEqual(needs["ai_index"], {"便携": 0.9})
        self.assertEqual(needs["scenario"], "户外")
        self.assertEqual(needs["ref_pic"], [{"url": "https://example.test/ref.png"}])
        self.assertEqual(images, [])
        self.assertEqual(diagnostics["unlinked_aesthetic_research"], [])
        self.assertEqual(diagnostics["unlinked_demand_research"], [])
        json.dumps((users, images, diagnostics), ensure_ascii=False, allow_nan=False)

    def test_many_to_many_links_preserve_user_boundaries_without_join_multiplication(self) -> None:
        source = snapshot(
            users=[user(1), user(2)],
            aesthetic_research=[question(11), question(12), question(13)],
            demands=[demand(21), demand(22)],
            aesthetic_links=[
                link(101, 1, "question-11"), link(102, 1, "question-12"),
                link(103, 2, "question-13"), link(104, 2, "question-12"),
                link(105, 1, "question-11"),
            ],
            demand_links=[
                link(201, 1, "demand-21"), link(202, 1, "demand-22"),
                link(203, 1, "demand-21"),
            ],
        )

        users, _, diagnostics = build_records(source)

        indexed = {entry["id"]: entry for entry in users}
        self.assertEqual({entry["id"] for entry in indexed["1"]["aesthetic_research"]}, {"11", "12"})
        self.assertEqual(len(indexed["1"]["aesthetic_research"]), 2)
        self.assertEqual({entry["id"] for entry in indexed["2"]["aesthetic_research"]}, {"12", "13"})
        self.assertEqual(len(indexed["2"]["aesthetic_research"]), 2)
        self.assertEqual({entry["id"] for entry in indexed["1"]["demand_research"]}, {"21", "22"})
        self.assertEqual(len(indexed["1"]["demand_research"]), 2)
        self.assertEqual(indexed["2"]["demand_research"], [])
        self.assertEqual(diagnostics["duplicate_relation_count"], 2)

    def test_missing_name_stays_null_without_affecting_user_links(self) -> None:
        source = snapshot(users=[user(1)], aesthetic_research=[question(11)],
                          aesthetic_links=[link(101, 1, "question-11")])
        users, _, _ = build_records(source)
        self.assertIsNone(users[0]["name"])
        self.assertEqual(users[0]["aesthetic_research"][0]["id"], "11")

    def test_name_refresh_preserves_other_snapshot_rows_and_rejects_identity_drift(self) -> None:
        source = snapshot(users=[user(1, country="Pakistan"), user(2, country="Indonesia")],
                          aesthetic_research=[question(11)])
        original_research = deepcopy(source["aesthetic_research"])
        merge_user_names(source, [user(1, name="M Aqib"), user(2, name="Irwanita")])
        self.assertEqual([row["name"] for row in source["users"]], ["M Aqib", "Irwanita"])
        self.assertEqual(source["aesthetic_research"], original_research)
        self.assertEqual(source["source"]["user_name_sync"]["query_version"], "user_names_v1")
        with self.assertRaisesRegex(ValueError, "ID/BID 不一致"):
            merge_user_names(source, [user(1, name="M Aqib"), user(3, name="Irwanita")])

    def test_deleted_users_source_records_and_relations_do_not_leak_into_output(self) -> None:
        source = snapshot(
            users=[user(1), user(2, delete_flag=1)],
            aesthetic_research=[question(11), question(12, delete_flag=1), question(13), question(14)],
            demands=[demand(21), demand(22, delete_flag=1), demand(23), demand(24)],
            aesthetic_links=[
                link(101, 1, "question-11"), link(102, 1, "question-12"),
                link(103, 1, "question-13", delete_flag=1), link(104, 2, "question-14"),
            ],
            demand_links=[
                link(201, 1, "demand-21"), link(202, 1, "demand-22"),
                link(203, 1, "demand-23", delete_flag=1), link(204, 2, "demand-24"),
            ],
            image_responses=[
                response(301, 1, "https://example.test/a.png"),
                response(302, 2, "https://example.test/a.png", "DISLIKE"),
                response(303, 1, "https://example.test/a.png", "DISLIKE", delete_flag=1),
            ],
        )

        users, images, diagnostics = build_records(source)

        self.assertEqual([entry["id"] for entry in users], ["1"])
        self.assertEqual([entry["id"] for entry in users[0]["aesthetic_research"]], ["11"])
        self.assertEqual([entry["id"] for entry in users[0]["demand_research"]], ["21"])
        self.assertEqual({str(entry["id"]) for entry in diagnostics["unlinked_aesthetic_research"]}, {"13", "14"})
        self.assertEqual({str(entry["id"]) for entry in diagnostics["unlinked_demand_research"]}, {"23", "24"})
        self.assertEqual(len(images), 1)
        self.assertEqual((images[0]["enjoy_count"], images[0]["dislike_count"]), (1, 0))
        self.assertEqual([entry["source_id"] for entry in images[0]["responses"]], ["301"])

    def test_orphan_research_is_retained_and_relation_direction_is_not_guessed(self) -> None:
        source = snapshot(
            users=[user(1)], aesthetic_research=[question(11), question(12)],
            demands=[demand(21), demand(22)],
            aesthetic_links=[
                link(101, 999, "question-11"),
                {"id": 102, "source_bid": "question-12", "target_bid": "user-1", "delete_flag": 0},
            ],
            demand_links=[link(201, 999, "demand-21"), link(202, 1, "nonexistent-demand")],
        )

        users, _, diagnostics = build_records(source)

        self.assertEqual(users[0]["aesthetic_research"], [])
        self.assertEqual(users[0]["demand_research"], [])
        self.assertEqual({str(entry["id"]) for entry in diagnostics["unlinked_aesthetic_research"]}, {"11", "12"})
        self.assertEqual({str(entry["id"]) for entry in diagnostics["unlinked_demand_research"]}, {"21", "22"})
        self.assertEqual(diagnostics["ignored_relation_count"], 4)

    def test_duplicate_active_business_ids_are_rejected_before_any_association(self) -> None:
        for table, rows in (
            ("users", [user(1), user(2, bid="user-1")]),
            ("aesthetic_research", [question(11), question(12, bid="question-11")]),
            ("demands", [demand(21), demand(22, bid="demand-21")]),
            ("image_responses", [
                response(301, 1, "https://example.test/a.png"),
                response(302, 1, "https://example.test/b.png", bid="response-301"),
            ]),
        ):
            with self.subTest(table=table), self.assertRaises(ValueError):
                build_records(snapshot(**{table: rows}))

    def test_deleted_duplicate_business_id_does_not_block_current_record(self) -> None:
        users, _, _ = build_records(snapshot(users=[user(1), user(2, bid="user-1", delete_flag=1)]))
        self.assertEqual([entry["id"] for entry in users], ["1"])

    def test_image_votes_count_source_rows_and_deduplicate_urls_within_each_response(self) -> None:
        image_a, image_b = "https://example.test/a.png", "https://example.test/b.png"
        attachments = json.dumps([
            {"name": "首图", "url": image_a}, {"name": "重复附件", "url": image_a},
            {"name": "次图", "url": image_b},
        ])
        source = snapshot(users=[user(1), user(2), user(3, delete_flag=1)], image_responses=[
            response(301, 1, attachments, " enjoy "),
            response(302, 1, image_a, "ENJOY"),
            response(303, 2, image_a, "DISLIKE"),
            response(304, 3, image_a, "DISLIKE"),
            response(305, 999, image_a, "DISLIKE"),
        ])

        users, images, _ = build_records(source)

        indexed = {entry["url"]: entry for entry in images}
        self.assertEqual(set(indexed), {image_a, image_b})
        self.assertEqual((indexed[image_a]["enjoy_count"], indexed[image_a]["dislike_count"]), (2, 1))
        self.assertEqual((indexed[image_b]["enjoy_count"], indexed[image_b]["dislike_count"]), (1, 0))
        self.assertEqual(set(indexed[image_a]["emotion_tag"]), {"ENJOY", "DISLIKE"})
        self.assertEqual(len(indexed[image_a]["emotion_tag"]), 2)
        for url, entry in indexed.items():
            self.assertEqual(entry["id"], "image_" + hashlib.sha256(url.encode()).hexdigest()[:24])
            self.assertIsNone(entry["local_path"])
            self.assertEqual(entry["status"], "pending")
        votes = {entry["source_id"]: entry for entry in indexed[image_a]["responses"]}
        self.assertEqual(len(indexed[image_a]["responses"]), 3)
        self.assertEqual(set(votes), {"301", "302", "303"})
        for source_id, user_id, tag in (("301", "1", "ENJOY"), ("302", "1", "ENJOY"), ("303", "2", "DISLIKE")):
            self.assertEqual(votes[source_id]["source_bid"], f"response-{source_id}")
            self.assertEqual(votes[source_id]["user_id"], user_id)
            self.assertEqual(votes[source_id]["user_bid"], f"user-{user_id}")
            self.assertEqual(votes[source_id]["emotion_tag"], tag)
        valid_image_ids = {entry["id"] for entry in images}
        for entry in users:
            self.assertTrue(entry["image_preferences"])
            self.assertTrue(all(preference["image_id"] in valid_image_ids for preference in entry["image_preferences"]))

    def test_empty_emotion_is_excluded_and_unknown_nonempty_emotion_does_not_inflate_votes(self) -> None:
        source = snapshot(users=[user(1)], image_responses=[
            response(301, 1, "https://example.test/empty.png", None),
            response(302, 1, "https://example.test/blank.png", "   "),
            response(303, 1, "https://example.test/neutral.png", "NEUTRAL"),
        ])

        _, images, _ = build_records(source)

        self.assertEqual([entry["url"] for entry in images], ["https://example.test/neutral.png"])
        self.assertEqual(images[0]["emotion_tag"], ["NEUTRAL"])
        self.assertEqual((images[0]["enjoy_count"], images[0]["dislike_count"]), (0, 0))

    def test_invalid_urls_are_diagnosed_without_discarding_other_valid_attachments(self) -> None:
        valid_url = "https://example.test/valid.png"
        source = snapshot(users=[user(1)], image_responses=[response(301, 1, json.dumps([
            {"url": valid_url}, {"url": "file:///tmp/private.png"}, {"url": "not-a-url"},
        ]))])

        _, images, diagnostics = build_records(source)

        self.assertEqual([entry["url"] for entry in images], [valid_url])
        self.assertEqual(len(diagnostics["invalid_image_urls"]), 2)
        for entry in diagnostics["invalid_image_urls"]:
            self.assertEqual(str(entry["source_id"]), "301")

    def test_empty_snapshot_and_missing_optional_profile_fields_are_json_serializable(self) -> None:
        users, images, diagnostics = build_records(snapshot())
        self.assertEqual((users, images), ([], []))
        self.assertEqual(diagnostics["unlinked_aesthetic_research"], [])
        self.assertEqual(diagnostics["unlinked_demand_research"], [])
        users, images, diagnostics = build_records(snapshot(users=[{"id": 1, "bid": "user-1"}]))
        self.assertEqual(users[0]["profile"], dict.fromkeys(EXPECTED_PROFILE_FIELDS))
        self.assertEqual(users[0]["aesthetic_research"], [])
        self.assertEqual(users[0]["demand_research"], [])
        self.assertEqual(users[0]["image_preferences"], [])
        json.dumps((users, images, diagnostics), ensure_ascii=False, allow_nan=False)

    def test_demand_image_codes_match_only_within_the_same_user_and_expose_ambiguity(self) -> None:
        source = snapshot(
            users=[user(1), user(2)], demands=[demand(21, ref_pic="P20，P21 P22 P20")],
            demand_links=[link(201, 1, "demand-21")],
            image_responses=[
                response(301, 1, "https://example.test/first-user.png", name="P20"),
                response(302, 2, "https://example.test/other-user.png", name="P21"),
                response(303, 1, "https://example.test/ambiguous-a.png", name="P22"),
                response(304, 1, "https://example.test/ambiguous-b.png", name="P22"),
            ],
        )

        users, images, diagnostics = build_records(source)

        indexed = {entry["url"]: entry["id"] for entry in images}
        references = users[0]["demand_research"][0]["ref_pic_links"]
        self.assertEqual(len(references), 3)
        by_code = {entry["code"]: entry for entry in references}
        self.assertEqual(by_code["P20"]["status"], "matched")
        self.assertEqual(by_code["P20"]["image_ids"], [indexed["https://example.test/first-user.png"]])
        self.assertEqual(by_code["P21"]["status"], "unmatched")
        self.assertEqual(by_code["P21"]["image_ids"], [])
        self.assertEqual(by_code["P22"]["status"], "ambiguous")
        self.assertEqual(set(by_code["P22"]["image_ids"]), {
            indexed["https://example.test/ambiguous-a.png"], indexed["https://example.test/ambiguous-b.png"],
        })
        self.assertEqual({entry["code"] for entry in diagnostics["unresolved_demand_image_references"]}, {"P21", "P22"})


class UserResearchImageDownloadTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.png = make_png(3, 2, (20, 100, 180))
        cls.requests = Counter()

        class ImageHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                cls.requests[self.path] += 1
                status, body = (404, b"missing") if self.path == "/missing.png" else (200, cls.png)
                self.send_response(status)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ImageHandler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output_dir = Path(directory.name)

    def image(self, endpoint: str) -> dict:
        _, images, _ = build_records(snapshot(users=[user(1)], image_responses=[
            response(301, 1, self.base_url + endpoint),
        ]))
        return images[0]

    def test_download_and_cache_preserve_image_identity_and_vote_sources(self) -> None:
        original = self.image("/download.png")

        result = download_research_image(original, self.output_dir, timeout=3, retries=0)

        self.assertEqual(result["status"], "downloaded", result)
        self.assertNotIn("trend_id", result)
        for field in ("id", "url", "emotion_tag", "enjoy_count", "dislike_count", "responses"):
            self.assertEqual(result[field], original[field])
        path = Path(result["local_path"])
        self.assertFalse(path.is_absolute())
        self.assertEqual(path.parts[0], "images")
        self.assertEqual((self.output_dir / path).read_bytes(), self.png)
        self.assertEqual((result["width"], result["height"]), (3, 2))
        self.assertEqual(result["sha256"], hashlib.sha256(self.png).hexdigest())
        requests_before = self.requests["/download.png"]
        cached = download_research_image(original, self.output_dir, timeout=3, retries=0)
        self.assertEqual(cached["status"], "downloaded", cached)
        self.assertEqual(cached["local_path"], result["local_path"])
        self.assertEqual(self.requests["/download.png"], requests_before)

    def test_failed_download_keeps_vote_metadata_and_no_local_path(self) -> None:
        original = self.image("/missing.png")

        result = download_research_image(original, self.output_dir, timeout=3, retries=0)

        self.assertEqual(result["status"], "failed", result)
        self.assertIsNone(result["local_path"])
        self.assertTrue(result["error"])
        self.assertNotIn("trend_id", result)
        self.assertEqual(result["id"], original["id"])
        self.assertEqual(result["responses"], original["responses"])
        self.assertEqual(result["enjoy_count"], 1)

    def write_source_snapshot(self) -> Path:
        source = snapshot(
            users=[user(1, country="中国")],
            aesthetic_research=[question(11)], demands=[demand(21, ref_pic="P20"), demand(22)],
            aesthetic_links=[link(101, 1, "question-11")],
            demand_links=[link(201, 1, "demand-21")],
            image_responses=[
                response(301, 1, self.base_url + "/main.png", "ENJOY", name="P20"),
                response(302, 1, self.base_url + "/missing.png", "DISLIKE", name="P21"),
            ],
        )
        source["source"] = {"host": "snapshot-fixture", "database": "fixture_database"}
        path = self.output_dir / "input_snapshot.json"
        path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def test_snapshot_replay_writes_consistent_tables_paths_counts_and_source_hash(self) -> None:
        source = self.write_source_snapshot()
        destination = self.output_dir / "prepared"
        arguments = [
            "--input-snapshot", str(source), "--output", str(destination),
            "--workers", "2", "--retries", "0", "--timeout", "3",
        ]
        with patch("scripts.prepare_user_research_data.fetch_source") as fetcher, redirect_stdout(io.StringIO()):
            exit_code = main(arguments)
        fetcher.assert_not_called()

        self.assertEqual(exit_code, 2)
        users_document = json.loads((destination / "users.json").read_text(encoding="utf-8"))
        images_document = json.loads((destination / "images.json").read_text(encoding="utf-8"))
        report = json.loads((destination / "export_report.json").read_text(encoding="utf-8"))
        for name, document in (("users", users_document), ("images", images_document)):
            lines = [json.loads(line) for line in (destination / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(document[name], lines)
            self.assertEqual(document["counts"], report["counts"])
            self.assertEqual(document["source"], report["source"])
        self.assertEqual([entry["id"] for entry in users_document["unlinked_demand_research"]], ["22"])
        self.assertEqual(users_document["unlinked_demand_research"], report["diagnostics"]["unlinked_demand_research"])
        images = {entry["id"]: entry for entry in images_document["images"]}
        for preference in users_document["users"][0]["image_preferences"]:
            self.assertEqual(preference["local_path"], images[preference["image_id"]]["local_path"])
        demand_link = users_document["users"][0]["demand_research"][0]["ref_pic_links"][0]
        self.assertEqual(demand_link["local_paths"], [images[identifier]["local_path"] for identifier in demand_link["image_ids"]])
        successful = next(entry for entry in images.values() if entry["status"] == "downloaded")
        failed = next(entry for entry in images.values() if entry["status"] == "failed")
        self.assertEqual((destination / successful["local_path"]).read_bytes(), self.png)
        self.assertIsNone(failed["local_path"])
        self.assertEqual([entry["id"] for entry in report["download_failures"]], [failed["id"]])
        expected_counts = {
            "users": 1, "aesthetic_research": 1, "demand_research": 1,
            "unlinked_demand_research": 1, "images": 2, "image_response_assignments": 2,
            "enjoy": 1, "dislike": 1, "downloaded": 1, "failed": 1, "pending": 0,
        }
        for field, expected in expected_counts.items():
            self.assertEqual(report["counts"][field], expected, field)
        source_metadata = report["source"]
        self.assertEqual((destination / source_metadata["snapshot_file"]).read_bytes(), source.read_bytes())
        self.assertEqual(source_metadata["snapshot_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

        requests_before = self.requests["/main.png"]
        with patch("scripts.prepare_user_research_data.fetch_source") as fetcher, redirect_stdout(io.StringIO()):
            self.assertEqual(main(arguments), 2)
        fetcher.assert_not_called()
        self.assertEqual(self.requests["/main.png"], requests_before)
        replay_report = json.loads((destination / "export_report.json").read_text(encoding="utf-8"))
        self.assertEqual(replay_report["counts"]["cached"], 1)

    def test_snapshot_dry_run_does_not_fetch_download_or_create_output(self) -> None:
        source = self.write_source_snapshot()
        destination = self.output_dir / "dry-run-output"
        with (
            patch("scripts.prepare_user_research_data.fetch_source") as fetcher,
            patch("scripts.prepare_user_research_data.download_research_image") as downloader,
            redirect_stdout(io.StringIO()),
        ):
            exit_code = main(["--input-snapshot", str(source), "--output", str(destination), "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(destination.exists())
        fetcher.assert_not_called()
        downloader.assert_not_called()

    def test_snapshot_name_refresh_dry_run_reads_names_without_writing(self) -> None:
        source = self.write_source_snapshot()
        destination = self.output_dir / "name-refresh-preview"
        with (
            patch("scripts.prepare_user_research_data.fetch_user_names", return_value=[user(1, name="Irwanita")]) as fetcher,
            patch("scripts.prepare_user_research_data.download_research_image") as downloader,
            redirect_stdout(io.StringIO()),
        ):
            exit_code = main(["--input-snapshot", str(source), "--refresh-user-names",
                              "--output", str(destination), "--dry-run"])
        self.assertEqual(exit_code, 0)
        self.assertFalse(destination.exists())
        fetcher.assert_called_once()
        downloader.assert_not_called()


class UserResearchDatabaseReadTestCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.env_file = Path(directory.name) / ".env"
        self.env_file.write_text(
            "USRDB_NAME=fixture_private_user\nUSRDB_PASS=fixture_private_password\n", encoding="utf-8",
        )
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value

    def assert_read_only_transaction_precedes_queries(self) -> list[str]:
        statements = [" ".join(call.args[0].upper().split()) for call in self.cursor.execute.call_args_list]
        first_select = next(index for index, statement in enumerate(statements) if statement.startswith("SELECT"))
        setup = statements[:first_select]
        self.assertTrue(any("REPEATABLE READ" in statement for statement in setup))
        self.assertTrue(any("READ ONLY" in statement for statement in setup))
        start = next(index for index, statement in enumerate(setup) if statement.startswith("START TRANSACTION"))
        self.assertIn("CONSISTENT SNAPSHOT", setup[start])
        self.assertTrue(any("READ ONLY" in statement for statement in setup[:start]))
        self.assertTrue(any("REPEATABLE READ" in statement for statement in setup[:start]))
        self.assertTrue(all(statement.startswith(("SET ", "START TRANSACTION", "SELECT ")) for statement in statements))
        return statements

    def test_fetch_uses_consistent_read_only_scope_and_does_not_export_credentials(self) -> None:
        self.cursor.fetchall.side_effect = [
            [user(1)], [question(11)], [demand(21)],
            [response(301, 1, "https://example.test/a.png")],
            [link(101, 1, "question-11")], [link(201, 1, "demand-21")],
        ]
        self.cursor.fetchone.return_value = {"count": 3}
        with patch("scripts.prepare_user_research_data.pymysql.connect", return_value=self.connection) as connect:
            result = fetch_source(self.env_file, host="fixture-db", port=3307, database="fixture_database")

        self.assertEqual(connect.call_args.kwargs["host"], "fixture-db")
        self.assertEqual(connect.call_args.kwargs["user"], "fixture_private_user")
        self.assertEqual(connect.call_args.kwargs["password"], "fixture_private_password")
        self.assertFalse(connect.call_args.kwargs["autocommit"])
        statements = self.assert_read_only_transaction_precedes_queries()
        user_select = next(statement for statement in statements if "FROM TRANSCEND_MODEL_ID_USER_DATA R" in statement)
        self.assertIn("R.NAME", user_select)
        image_select = next(statement for statement in statements if "FROM TRANSCEND_MODEL_IDUSERREFPIC " in statement and "COUNT(*)" not in statement)
        self.assertIn("EMOTION_TAG", image_select)
        self.assertIn("TRIM(", image_select)
        self.assertIn("IS NOT NULL", image_select)
        self.assertIn("FROM TRANSCEND_MODEL_ID_USER_DATA", image_select)
        self.assertIn("ID_USER_BID", image_select)
        # 两端均过滤逻辑删除，图片反馈才与用户表的统计范围一致。
        self.assertGreaterEqual(len(re.findall(r"\bDELETE_FLAG\s*=\s*0", image_select)), 2)
        self.assertEqual(result["users"][0]["id"], 1)
        self.assertEqual(result["scope_stats"]["excluded_user_image_responses"], 2)
        serialized = json.dumps(result, ensure_ascii=False)
        for secret in ("fixture_private_user", "fixture_private_password", "USRDB_NAME", "USRDB_PASS"):
            self.assertNotIn(secret, serialized)
        self.connection.rollback.assert_called_once_with()
        self.connection.close.assert_called_once_with()
        self.connection.commit.assert_not_called()

    def test_read_failure_rolls_back_and_closes_without_committing(self) -> None:
        self.cursor.fetchall.side_effect = RuntimeError("fixture read failure")
        with patch("scripts.prepare_user_research_data.pymysql.connect", return_value=self.connection):
            with self.assertRaisesRegex(RuntimeError, "fixture read failure"):
                fetch_source(self.env_file)

        self.assert_read_only_transaction_precedes_queries()
        self.connection.rollback.assert_called_once_with()
        self.connection.close.assert_called_once_with()
        self.connection.commit.assert_not_called()

    def test_fetch_user_names_reads_only_id_bid_name(self) -> None:
        self.cursor.fetchall.return_value = [user(1, name="Qasim Raza")]
        with patch("scripts.prepare_user_research_data.pymysql.connect", return_value=self.connection):
            rows = fetch_user_names(self.env_file)
        statements = self.assert_read_only_transaction_precedes_queries()
        selects = [statement for statement in statements if statement.startswith("SELECT")]
        self.assertEqual(len(selects), 1)
        self.assertIn("SELECT ID, BID, NAME FROM TRANSCEND_MODEL_ID_USER_DATA", selects[0])
        self.assertEqual(rows[0]["name"], "Qasim Raza")
        self.connection.rollback.assert_called_once_with()
        self.connection.close.assert_called_once_with()
        self.connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""工程传输注入的极小离线回归；合成回执不代表真实模型或审美质量。"""

import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("grouping_engineering_fixtures", Path(__file__).with_name("test_llm_group.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
group = fixtures.group


class SDKFixture(fixtures.FakeModel):
    """仅仿真工程执行器的原始证据格式，所有数据均在临时目录。"""

    def __init__(self, config):
        super().__init__()
        self.config = config

    def __call__(self, folder, *, system, payload, images, schema):
        answer = super().__call__(folder, system=system, payload=payload, images=images, schema=schema)
        text = json.dumps(payload, ensure_ascii=False) + "\n\n=== OUTPUT JSON SCHEMA ===\n" + json.dumps(schema)
        (folder / "prompt.txt").write_text(system + "\n=== ACTUAL PAYLOAD ===\n" + text)
        content = [{"type": "text", "text": text}]
        content.extend({"type": "image", "base64": base64.b64encode(Path(row["path"]).read_bytes()).decode(),
                        "mime_type": "image/png"} for row in images)
        group.write_new(folder / "sdk-request.json", {"model_id": self.config["model"],
                         "model_options": self.config["model_options"], "messages": [
                             {"role": "system", "content": system}, {"role": "user", "content": content}]})
        response_metadata = {"model_name": "provider-versioned-alias"}
        group.write_new(folder / "response.json", [{"response_metadata": response_metadata, "content": json.dumps(answer)}])
        request = {**{key: self.config[key] for key in ("runtime_ref", "transport", "actual_model_policy",
                                                        "model_options", "configuration_refs")},
                   "requested_model": self.config["model"], "requested_reasoning_effort": self.config["reasoning_effort"],
                   "actual_model": None, "started_at": "2026-10-21T00:00:00+00:00", "images": images,
                   "schema_ref": group.reference(folder / "schema.json"), "prompt_ref": group.reference(folder / "prompt.txt"),
                   "sdk_request_ref": group.reference(folder / "sdk-request.json")}
        receipt = {**request, "status": "completed", "answer_ref": group.reference(folder / "answer.json"),
                   "response_ref": group.reference(folder / "response.json"), "actual_model": "provider-versioned-alias",
                   "provider_response_metadata": response_metadata}
        for name, value in (("request.json", request), ("receipt.json", receipt)):
            (folder / name).write_text(json.dumps(value))
        return answer


class EngineeringExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = {"model": "fixture-model", "reasoning_effort": None,
                       "runtime_ref": group.reference(Path(__file__)), "transport": "project_langchain_sdk",
                       "actual_model_policy": "provider_reported", "model_options": {"max_retries": 0},
                       "configuration_refs": [group.reference(group.SCRIPT)]}
        self.rows = fixtures.cards(self.root, count=2)
        self.task = group.task("discover", {"branch": "CMF", "cards": [group.compact_card(row) for row in self.rows]},
                               group.DISCOVERY_SCHEMA, [group.reference(Path(self.rows[0]["local_path"]))])

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, config=None, callback=None):
        config = self.config if config is None else config
        return group.ModelCalls(self.root / "run", "合成离线规则", workers=1, max_calls=5,
                                execute=SDKFixture(config), execution_config=config, progress_callback=callback)

    def test_alias_verified_and_success_reused_with_live_progress(self):
        events = []
        first = self.runner(callback=events.append)
        result = first.run([self.task])[0]
        self.assertEqual(result["record"]["status"], "completed")
        self.assertEqual([row["event"] for row in events], ["batch_started", "call_started", "call_finished", "batch_finished"])
        self.assertEqual(events[-1]["call_status_counts"], {"completed": 1})
        second = self.runner()
        reused = second.run([self.task])[0]
        self.assertEqual(reused["record"]["status"], "cached")
        self.assertEqual(second.attempted, 0)
        plan = json.loads(next((self.root / "run/requests").glob("*.json")).read_text())
        self.assertEqual(plan["execution_config"], self.config)

    def test_config_changes_input_key_and_model_execution(self):
        first = self.runner().run([self.task])[0]
        config = copy.deepcopy(self.config)
        config["model_options"]["temperature"] = 0.2
        second = self.runner(config).run([self.task])[0]
        self.assertNotEqual(first["record"]["input_key"], second["record"]["input_key"])
        self.assertEqual(second["record"]["status"], "completed")

    def test_forged_actual_model_is_not_accepted_under_provider_reported(self):
        result = self.runner().run([self.task])[0]
        path = Path(result["record"]["path"]) / "receipt.json"
        receipt = json.loads(path.read_text())
        receipt["actual_model"] = "unbound-model"
        path.write_text(json.dumps(receipt))
        retry = self.runner().run([self.task])[0]
        self.assertEqual(retry["record"]["status"], "failed_existing_no_retry")
        self.assertIn("供应商原始响应", retry["record"]["reason"])

    def test_sdk_actual_messages_and_image_bytes_are_checked(self):
        result = self.runner().run([self.task])[0]
        folder = Path(result["record"]["path"])
        path = folder / "sdk-request.json"
        sdk = json.loads(path.read_text())
        sdk["messages"][1]["content"][1]["base64"] = base64.b64encode(b"different image").decode()
        path.write_text(json.dumps(sdk))
        for name in ("request.json", "receipt.json"):
            path = folder / name
            metadata = json.loads(path.read_text())
            metadata["sdk_request_ref"] = group.reference(folder / "sdk-request.json")
            path.write_text(json.dumps(metadata))
        rejected = self.runner().run([self.task])[0]
        self.assertEqual(rejected["record"]["status"], "failed_existing_no_retry")
        self.assertIn("附件字节", rejected["record"]["reason"])

    def test_engineering_requires_executor_and_progress_failure_is_observational(self):
        with self.assertRaisesRegex(ValueError, "执行函数"):
            group.ModelCalls(self.root / "run", "", execution_config=self.config)

        def broken_callback(event):
            raise RuntimeError("synthetic notification failure")

        calls = self.runner(callback=broken_callback)
        result = calls.run([self.task])[0]
        self.assertEqual(result["record"]["status"], "completed")
        self.assertEqual(len(calls.progress_errors), 4)

    def test_legacy_cli_still_uses_original_model_and_cache(self):
        fake = fixtures.FakeModel()
        calls = group.ModelCalls(self.root / "legacy", "合成离线规则", execute=fake)
        result = calls.run([self.task])[0]
        self.assertEqual(result["record"]["status"], "completed")
        cached = group.ModelCalls(self.root / "legacy", "合成离线规则", execute=fake).run([self.task])[0]
        self.assertEqual(cached["record"]["status"], "cached")


if __name__ == "__main__":
    unittest.main()

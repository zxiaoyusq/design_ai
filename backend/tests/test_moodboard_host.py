"""旧宿主不得绕过新版入口发布；仅读取已有原生交接，不发送模型。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import run_moodboard_host as host


class MoodboardHostTests(unittest.TestCase):
    def test_legacy_prepare_and_publish_do_not_touch_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            record = root / 'historical.json'
            record.write_text('{"status":"completed","legacy":true}')
            original = record.read_bytes()
            with self.assertRaisesRegex(RuntimeError, '已停用'):
                host.prepare()
            with self.assertRaisesRegex(RuntimeError, '已停用'):
                host.publish(root)
            self.assertEqual(record.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [record])

    def test_native_host_only_reads_verified_projection(self):
        result = {'directions': [], 'trace': {'new_model_calls': 0}}
        with patch('sys.argv', ['run_moodboard_host.py', '--preview-native-run', 'saved-run']), \
                patch('app.services.visual_workflow.web_adapter.preview_handoff', return_value=result) as preview, \
                patch('builtins.print') as output:
            host.main()
            preview.assert_called_once_with('saved-run')
            self.assertIn('"new_model_calls": 0', output.call_args.args[0])

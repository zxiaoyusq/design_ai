"""微型离线检查：图片重编译不能覆盖已确认的局部正文修订。"""

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from scripts.recompile_high_trend_images import published_text


class PublishedTextTests(unittest.TestCase):
    def test_revision_is_reused_and_changed_or_external_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            path = run / "revision.md"
            raw = "## 几何图案\n单一主题的修订。".encode()
            path.write_bytes(raw)
            revision = {"text_file": path.name, "text_sha256": sha256(raw).hexdigest()}
            manifest = {"output_revision": revision}
            receipt = {"text": "旧的混合主题"}
            self.assertEqual(published_text(run, {}, receipt), receipt["text"])
            self.assertEqual(published_text(run, manifest, receipt), raw.decode())
            path.write_text("被改动的修订")
            with self.assertRaisesRegex(ValueError, "不一致"):
                published_text(run, manifest, receipt)
            revision["text_file"] = "../outside.md"
            with self.assertRaisesRegex(ValueError, "本任务目录"):
                published_text(run, manifest, receipt)


if __name__ == "__main__":
    unittest.main()

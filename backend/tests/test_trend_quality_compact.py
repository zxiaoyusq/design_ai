"""极简输出不能掩盖未决、截断或失败；缩图保留上下文。"""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from PIL import Image
from app.agents.trend_quality import prepare_image, compact, SingleRequestTelemetry
from prism_runtime.quality.adapter import export_existing_result


class CompactQualityTests(TestCase):
    def test_compact_export_needs_no_invented_reason(self):
        image = {'image_id': 'fixture', 'source_kind': 'trend',
                 'provenance': {'verified': True, 'source_ref': 'offline-fixture'}}
        record = {'image_id': 'fixture', 'version': compact.VERSION, 'valid': True,
                  'status': 'complete', 'decision': 'PASS', 'raw_response': 'PASS',
                  'production_admission': False}
        result = export_existing_result(image, record, source_ref='fixture.json')
        self.assertEqual(result['decision'], 'PASS')
        self.assertEqual(result['reason'], '')
        self.assertEqual(result['reason_source'], 'not_requested')
        self.assertFalse(result['production_admission'])
        record['version'] = 'legacy-version'
        self.assertNotEqual(export_existing_result(image, record, source_ref='fixture.json')['status'], 'complete')

    def test_only_exact_verdict_is_accepted(self):
        self.assertEqual(compact.evaluate(' PASS\n')['decision'], 'PASS')
        self.assertEqual(compact.evaluate('FAIL')['decision'], 'FAIL')
        for raw in ('NOT PASS', 'PASS because...', '{"pass":true}', None, ''):
            self.assertEqual(compact.evaluate(raw)['status'], 'invalid_output')
        self.assertEqual(compact.evaluate('PASS', truncated=True)['status'], 'invalid_output')
        self.assertEqual(compact.evaluate('REVIEW')['status'], 'needs_review')
        self.assertIsNone(compact.evaluate('REVIEW')['decision'])

    def test_resize_keeps_ratio_corners_and_alpha(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'large.png'
            source = Image.new('RGBA', (2400, 1200), (0, 0, 0, 0))
            source.paste((255, 0, 0, 255), (0, 0, 100, 100))
            source.paste((0, 0, 255, 255), (2300, 1100, 2400, 1200))
            source.save(path)
            data, metadata = prepare_image(path)
        image = Image.open(BytesIO(data))
        self.assertEqual(image.size, (1600, 800))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((1599, 799)), (0, 0, 255, 255))
        self.assertEqual(image.getpixel((800, 400))[3], 0)
        self.assertNotEqual(metadata['image_sha256'], metadata['input_image_sha256'])

    def test_small_image_bytes_are_preserved_without_upscale(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'small.jpg'
            Image.new('RGB', (320, 480)).save(path)
            data, metadata = prepare_image(path)
            self.assertEqual(data, path.read_bytes())
            self.assertEqual(metadata['input_pixels'], [320, 480])

    def test_orientation_is_applied_before_resize(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'rotated.jpg'
            image = Image.new('RGB', (900, 600))
            exif = image.getexif()
            exif[274] = 6
            image.save(path, exif=exif)
            data, metadata = prepare_image(path)
        self.assertEqual(Image.open(BytesIO(data)).size, (600, 900))
        self.assertEqual(metadata['input_pixels'], [600, 900])

    def test_internal_retry_is_blocked(self):
        callback = SingleRequestTelemetry()
        callback.on_chat_model_start({}, [], run_id=None)
        with self.assertRaises(RuntimeError):
            callback.on_chat_model_start({}, [], run_id=None)

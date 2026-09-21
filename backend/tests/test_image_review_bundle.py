"""用微型图片验证跨目录部署、来源保存及无损拒绝覆盖。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('image_review_bundle', Path(__file__).parents[1] / 'scripts/image_review_bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class ImageReviewBundleTests(unittest.TestCase):
    def test_encrypted_round_trip_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = 'web_' + 'b' * 32
            run = root / 'source/data/result/high_trend' / task
            for collection in bundle.COLLECTIONS:
                images = run / collection / 'images'
                images.mkdir(parents=True)
                image = images / 'example.png'
                image.write_bytes(b'tiny-image-fixture')
                bundle.write_json(images.parent / 'review.json', {
                    'revision': 3, 'folder': '/old/computer',
                    'images': [{'copy_path': 'images/example.png', 'sha256': bundle.digest(image),
                                'retained': True, 'origins': [{'original_path': '/old/source.png'}]}]})
            bundle.write_json(run / 'web_task.json', {'id': task, 'status': 'completed'})
            manifest = bundle.pack(root / 'source', task, root / 'bundle', 'test', password='test-password', part_bytes=150)
            target = root / 'target'
            with self.assertRaises(Exception):
                bundle.restore(target, manifest, root / 'bundle', password='wrong-password', local_only=True)
            self.assertFalse((target / 'data/result/high_trend' / task).exists())
            restored = bundle.restore(target, manifest, root / 'bundle', password='test-password', local_only=True)
            for collection in bundle.COLLECTIONS:
                review = json.loads((restored / collection / 'review.json').read_text())
                self.assertEqual(review['folder'], str(restored / collection))
                self.assertTrue(review['images'][0]['retained'])
                self.assertEqual(review['images'][0]['origins'][0]['original_path'], '/old/source.png')
            with self.assertRaises(FileExistsError):
                bundle.restore(target, manifest, root / 'bundle', password='test-password', local_only=True)
            corrupted = root / 'bundle' / manifest['assets'][0]['name']
            corrupted.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, '校验失败'):
                bundle.restore(root / 'another', manifest, root / 'bundle', password='test-password', local_only=True)

    def test_path_traversal_rejected(self):
        for value in ['/etc/passwd', '../outside', 'images/../../outside', 'images\\outside', '']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                bundle.safe_path(value)


if __name__ == '__main__':
    unittest.main()

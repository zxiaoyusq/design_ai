"""人工状态不可混同模型结果，批量写入和版本冲突不得造成部分覆盖。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from PIL import Image

from app.services.high_trends.image_review import file_hash, write_atomic, read
from app.services.trend_quality_review import TrendQualityReview, COLLECTION_ID


class TrendQualityReviewTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = TrendQualityReview(self.root)
        self.service.folder.mkdir(parents=True)
        images = []
        for index, category in enumerate(('PASS', 'FAIL')):
            path = self.root / 'data/trend_data/images' / f'{index}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (20, 30), (index * 200, 0, 0)).save(path)
            digest = file_hash(path)
            images.append({'id': digest, 'image_id': str(index), 'image_ids': [str(index)],
                'article_title': '合成文章', 'articles': [{'id': 'fixture', 'title': '合成文章', 'url': None}],
                'directions': [{'id': 'H001', 'title': '合成方向'}], 'source_path': str(path.relative_to(self.root)),
                'model_category': category, 'model_status': 'complete', 'model_decision': category})
        self.images = images
        catalog = self.service.folder / 'catalog.json'
        write_atomic(catalog, {'collection_id': COLLECTION_ID, 'title': '合成图库', 'images': images, 'source_batches': []})
        write_atomic(self.service.folder / 'selections.json', {'catalog_sha256': file_hash(catalog),
            'revision': 1, 'updated_at': 'fixture', 'labels': {}, 'history': []})

    def tearDown(self):
        self.temporary.cleanup()

    def test_model_pass_is_unreviewed_and_not_exported_as_manual_pass(self):
        page = self.service.page(model_category='PASS')
        self.assertEqual(page['filtered_count'], 1)
        self.assertIsNone(page['images'][0]['manual_decision'])
        self.assertEqual(page['counts']['manual']['unreviewed'], 2)
        self.assertEqual(self.service.download('PASS')['images'], [])

    def test_manual_choice_survives_new_service_and_preserves_model_result(self):
        digest = self.images[0]['id']
        self.service.update(1, [digest], 'FAIL')
        resumed = TrendQualityReview(self.root)
        page = resumed.page(manual='FAIL')
        self.assertEqual(page['images'][0]['model_decision'], 'PASS')
        self.assertEqual(page['images'][0]['manual_decision'], 'FAIL')
        self.assertEqual(len(resumed.download('FAIL')['images']), 1)
        resumed.update(2, [digest], None)
        self.assertEqual(resumed.page()['counts']['manual']['unreviewed'], 2)
        self.assertEqual(len(read(resumed.folder / 'selections.json')['history']), 2)

    def test_stale_revision_and_unknown_batch_id_leave_all_choices_intact(self):
        digest = self.images[0]['id']
        self.service.update(1, [digest], 'PASS')
        with self.assertRaises(RuntimeError):
            self.service.update(1, [digest], 'FAIL')
        with self.assertRaises(ValueError):
            self.service.update(2, [digest, 'unknown'], 'FAIL')
        self.assertEqual(self.service.page(manual='PASS')['filtered_count'], 1)
        self.assertEqual(self.service.page()['revision'], 2)

    def test_original_image_replacement_is_rejected(self):
        digest = self.images[0]['id']
        original = self.service.image(digest)
        original.write_bytes(b'changed')
        with self.assertRaises(RuntimeError):
            self.service.image(digest)
        with self.assertRaises(FileNotFoundError):
            self.service.image('../catalog.json')

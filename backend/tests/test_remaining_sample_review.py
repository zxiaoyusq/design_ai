"""验证新旧人工审核集合隔离、剩余图缩略图和集合参数路由，不写生产状态。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api import trend_quality_review as api
from app.services.high_trends.image_review import file_hash, read, write_atomic
from app.services.trend_quality_review import COLLECTION_ID, REMAINING_COLLECTION_ID, TrendQualityReview


class RemainingReviewTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        original = self.root / 'data/trend_data/images/shared.png'
        original.parent.mkdir(parents=True)
        Image.new('RGB', (40, 70), 'white').save(original)
        self.sha = file_hash(original)
        row = {'id': self.sha, 'image_id': 'fixture_001', 'image_ids': ['fixture_001'],
               'source_path': str(original.relative_to(self.root)),
               'snapshot_path': str(original.relative_to(self.root)), 'input_image_sha256': self.sha,
               'article_title': '合成来源', 'articles': [{'id': 'fixture', 'title': '合成来源', 'url': None}],
               'directions': [{'id': 'H01-01', 'title': '合成方向'}],
               'model_category': 'REVIEW', 'model_status': 'not_evaluated', 'model_decision': None}
        self.old = TrendQualityReview(self.root)
        self.new = TrendQualityReview(self.root, REMAINING_COLLECTION_ID)
        for service in (self.old, self.new):
            service.folder.mkdir(parents=True)
            catalog = service.folder / 'catalog.json'
            write_atomic(catalog, {'collection_id': service.collection_id, 'title': '合成图库',
                                   'source_batches': [], 'images': [deepcopy(row)]})
            write_atomic(service.folder / 'selections.json', {'collection_id': service.collection_id,
                'catalog_sha256': file_hash(catalog), 'revision': 1, 'updated_at': 'fixture',
                'labels': {}, 'history': []})

    def test_same_sha_has_independent_persistent_labels(self):
        self.old.update(1, [self.sha], 'FAIL')
        self.assertIsNone(self.new.page()['images'][0]['manual_decision'])
        self.new.update(1, [self.sha], 'PASS')
        resumed = TrendQualityReview(self.root, REMAINING_COLLECTION_ID)
        self.assertEqual(resumed.page()['counts']['manual']['PASS'], 1)
        self.assertEqual(self.old.page()['counts']['manual']['FAIL'], 1)
        with self.assertRaises(RuntimeError):
            resumed.update(1, [self.sha], 'FAIL')
        self.assertEqual(resumed.download('PASS')['collection_id'], REMAINING_COLLECTION_ID)
        self.assertEqual(self.old.download('PASS')['images'], [])
        resumed.update(2, [self.sha], None)
        self.assertEqual(resumed.page()['counts']['manual']['unreviewed'], 1)

    def test_remaining_thumbnail_uses_original_and_urls_keep_collection(self):
        image = self.new.page()['images'][0]
        self.assertIn(f'?collection={REMAINING_COLLECTION_ID}', image['image_url'])
        self.assertIn('&thumbnail=true', image['thumbnail_url'])
        self.assertNotIn('collection=', self.old.page()['images'][0]['image_url'])
        thumbnail = self.new.image(self.sha, thumbnail=True)
        with Image.open(thumbnail) as decoded:
            self.assertEqual(decoded.size, (40, 70))
        self.assertEqual(file_hash(self.new.image(self.sha)), self.sha)

    def test_api_routes_save_export_and_reject_unknown_collection(self):
        app = FastAPI()
        app.include_router(api.router, prefix='/api/v1')
        with patch.object(api, 'service', self.old), patch.object(api, 'remaining_service', self.new), TestClient(app) as client:
            base = '/api/v1/trend-quality/review'
            params = {'collection': REMAINING_COLLECTION_ID}
            response = client.get(base, params=params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['counts']['manual']['unreviewed'], 1)
            saved = client.patch(base, params=params, json={'revision': 1, 'image_ids': [self.sha], 'decision': 'PASS'})
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(client.get(base, params=dict(params, manual='PASS')).json()['filtered_count'], 1)
            exported = client.get(base + '/download', params=dict(params, selection='PASS'))
            self.assertEqual(exported.json()['images'][0]['manual_decision'], 'PASS')
            self.assertEqual(client.get(base).json()['counts']['manual']['unreviewed'], 1)
            self.assertEqual(client.get(base, params={'collection': '../elsewhere'}).status_code, 422)
            self.assertEqual(client.patch(base, params=params, json={'revision': 1, 'image_ids': [self.sha], 'decision': 'FAIL'}).status_code, 409)
            self.assertEqual(len(read(self.new.folder / 'selections.json')['history']), 1)

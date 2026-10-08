"""用临时目录与假调用验证趋势R5范围、冻结和不重试。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from PIL import Image
from scripts import run_trend_r5_batch as batch

class TrendR5BatchTest(TestCase):
    def test_union_model_pass_human_fail_and_manual_priority(self):
        catalog = {'images': [{'id': 'a', 'model_category': 'PASS'}, {'id': 'b', 'model_category': 'FAIL'},
                              {'id': 'c', 'model_category': 'FAIL'}, {'id': 'd', 'model_category': 'PASS'}]}
        state = {'labels': {'a': {'decision': 'FAIL'}, 'b': {'decision': 'PASS'}}}
        selected, total = batch.select_images(catalog, state, limit=2)
        self.assertEqual([item['id'] for item in selected], ['b', 'a'])
        self.assertEqual(total, 3)

    def test_originals_frozen_and_resume_does_not_reselect_after_human_changes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); review = root / 'review'; review.mkdir(); folder = root / 'batch'
            images = []
            for number in range(3):
                source = root / 'data/trend_data/images' / f'{number}.png'
                source.parent.mkdir(parents=True, exist_ok=True)
                Image.new('RGB', (3, 3), (number, 20, 40)).save(source)
                images.append({'id': batch.sha(source), 'image_id': str(number),
                               'source_path': str(source.relative_to(root)),
                               'model_category': 'PASS', 'model_decision': 'PASS'})
            batch.save(review / 'catalog.json', {'images': images})
            state = {'catalog_sha256': batch.sha(review / 'catalog.json'), 'revision': 1, 'labels': {}}
            batch.save(review / 'selections.json', state)
            with patch.multiple(batch, ROOT=root, REVIEW=review, FOLDER=folder, LIMIT=3, RESULT_DIR=root / "data/result/d02"), \
                    patch.object(batch, 'runtime_files', return_value={}):
                first = batch.prepare()
                state.update(revision=2, labels={images[0]['id']: {'decision': 'FAIL'}})
                batch.save(review / 'selections.json', state)
                second = batch.prepare()
                self.assertEqual(first, second)
                self.assertEqual(second['manual_revision'], 1)
                for entry in second['entries']:
                    self.assertEqual(batch.sha(folder / entry['snapshot']), entry['sha256'])

    def test_failure_submitted_once_and_resume_only_processes_pending(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            entries = [{'entry_id': str(n), 'image_id': str(n), 'sha256': str(n),
                        'status': 'pending', 'error': None} for n in range(7)]
            manifest = {'batch_id': batch.BATCH_ID, 'status': 'prepared', 'model_id': batch.MODEL,
                        'max_concurrency': 5, 'selected_count': 7, 'created_at': batch.now(),
                        'stopped_reason': None, 'entries': entries}
            batch.save(folder / 'selection.json', {'images': [{'id': str(n)} for n in range(7)]})
            submitted = []
            def fake(entry, lineage):
                submitted.append(entry['image_id'])
                return {'status': 'failed' if entry['image_id'] == '0' else 'completed',
                        'error': 'Connection error' if entry['image_id'] == '0' else None}
            with patch.object(batch, 'FOLDER', folder), patch.object(batch, 'prepare', return_value=manifest), \
                    patch.object(batch, 'run_one', side_effect=fake):
                batch.execute(); batch.execute()
            self.assertEqual(sorted(submitted), list('0123456'))
            self.assertEqual(manifest['counts']['failed'], 1)
            self.assertEqual(manifest['counts']['completed'], 6)

    def test_interrupted_submission_without_result_becomes_failed(self):
        with TemporaryDirectory() as directory:
            manifest = {'entries': [{'sha256': 'a', 'status': 'running'}]}
            with patch.object(batch, 'RESULT_DIR', Path(directory)):
                batch.recover(manifest)
            self.assertEqual(manifest['entries'][0]['status'], 'failed')

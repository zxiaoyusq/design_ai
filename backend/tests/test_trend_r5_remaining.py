"""剩余GPT批次只用假请求验证并集范围、十路上限及不重试。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import sleep
from unittest import TestCase
from unittest.mock import patch
from scripts import run_trend_r5_remaining as batch


class TrendR5RemainingTests(TestCase):
    def test_all_remaining_excludes_every_previously_submitted_status(self):
        images = [{'id': str(i), 'model_category': 'PASS'} for i in range(8)]
        images.append({'id': 'human-only', 'model_category': 'FAIL'})
        state = {'labels': {'human-only': {'decision': 'PASS'}, '7': {'decision': 'FAIL'}}}
        previous = {'entries': [{'sha256': str(i), 'status': status} for i, status in enumerate(
            ['completed', 'partial', 'failed', 'running', 'pending'])]}
        remaining, excluded, total = batch.select_remaining({'images': images}, state, previous)
        self.assertEqual([r['id'] for r in remaining], ['human-only', '4', '5', '6', '7'])
        self.assertEqual(excluded, {'0', '1', '2', '3'})
        self.assertEqual(total, 9)

    def test_ten_workers_with_one_submission_per_image_and_resume_no_retry(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp) / 'batch'; folder.mkdir()
            entries = [{'entry_id': str(i), 'image_id': str(i), 'sha256': str(i), 'status': 'pending'} for i in range(23)]
            manifest = {'entries': entries, 'selected_count': len(entries), 'frozen_files': {'selection.json': 'test'}}
            batch.save(folder / 'progress.json', {'stopped_reason': None})
            batch.save(folder / 'selection.json', {'images': [{'id': str(i)} for i in range(23)]})
            submitted = []; gate = Lock(); active = 0; peak = 0
            def fake(row, lineage, digest):
                nonlocal active, peak
                self.assertEqual(batch.read(folder/'entries'/(row['entry_id']+'.json'))['status'], 'running')
                with gate:
                    submitted.append(row['image_id']); active += 1; peak = max(peak, active)
                sleep(.04)
                with gate: active -= 1
                return {'status': 'failed' if row['image_id'] == '0' else 'completed',
                        'raw_status': 'failed' if row['image_id'] == '0' else 'completed', 'error': None}
            with patch.object(batch, 'FOLDER', folder), patch.object(batch, 'prepare', return_value=manifest), \
                 patch.object(batch, 'run_one', side_effect=fake), patch('builtins.print'):
                first = batch.execute(); batch.execute()
            self.assertEqual(len(submitted), 23); self.assertEqual(len(set(submitted)), 23)
            self.assertLessEqual(peak, 10); self.assertGreater(peak, 5)
            self.assertEqual(first['counts']['failed'], 1)
            self.assertEqual(first['counts']['completed'], 22)

    def test_local_repair_records_original_failure_and_does_not_invoke_model(self):
        with TemporaryDirectory() as temp:
            entry = {'entry_id': 'I00001', 'sha256': 'hash', 'image_id': 'img', 'status': 'running'}
            outcome = {'status': 'failed', 'trace_id': 'trace', 'error': 'schema-invalid'}
            repaired = {'status': 'recovered_partial', 'validation': {'quarantined_count': 1, 'pending_count': 2}}
            with patch.object(batch, 'FOLDER', Path(temp)), patch.object(batch, 'ROOT', Path(temp)), \
                 patch.object(batch, 'recover_entry', return_value=repaired) as repair, \
                 patch.object(batch, 'run_prism_r5_extraction', side_effect=AssertionError('不能调用模型')):
                result = batch.repair_outcome(entry, outcome)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['raw_status'], 'failed')
            self.assertTrue(result['repair_applied'])
            self.assertEqual(repair.call_args.kwargs['expected_model'], 'gpt-6-sol')

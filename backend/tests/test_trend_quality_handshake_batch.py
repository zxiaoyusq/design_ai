"""用假模型验证批次额度、5路并发、失败跳过与断点不重发。"""

import asyncio
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_trend_quality_handshake_batch.py'
spec = importlib.util.spec_from_file_location('quality_handshake_batch', SCRIPT)
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class HandshakeBatchTests(IsolatedAsyncioTestCase):
    def fixture(self, directory):
        directory = Path(directory)
        images = []
        for index in range(7):
            path = directory / f'{index}.jpg'
            Image.new('RGB', (32, 32), (index * 20, 0, 0)).save(path)
            images.append({'image_id': f'fixture_{index}', 'status': 'downloaded',
                           'local_path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()})
        source = directory / 'source.json'
        source.write_text(json.dumps({'schema_version': 'prism.h01.related_trend_articles.v1',
                                     'articles': [{'source_id': 'T:fixture', 'original_id': 'fixture',
                                                   'title': '离线夹具', 'images': images + [images[0]]}]}))
        return source

    async def test_five_workers_stop_at_limit_and_failed_image_is_not_retried(self):
        with TemporaryDirectory(dir=batch.ROOT / 'data/trend_data/images') as temporary:
            source = self.fixture(temporary)
            folder = Path(temporary) / 'batch'
            batch.prepare(source, folder, limit=5, concurrency=5)
            active, maximum, calls = 0, 0, []

            async def fake_call(data, metadata, *, image_id, model_id):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                calls.append(image_id)
                await asyncio.sleep(0.01)
                active -= 1
                failed = image_id == 'fixture_0'
                return {'decision': None if failed else 'PASS',
                        'status': 'execution_error' if failed else 'complete',
                        'usage': {'llm_request_count': 1}, 'duration_seconds': 0.01}

            with patch.object(batch.quality, 'classify', side_effect=fake_call):
                await batch.execute(folder)
                await batch.execute(folder)
            self.assertEqual(len(calls), 5)
            self.assertEqual(len(set(calls)), 5)
            self.assertEqual(maximum, 5)
            failed = json.loads((folder / 'failed.json').read_text())
            self.assertEqual(len(failed), 1)
            summary = json.loads((folder / 'summary.json').read_text())
            self.assertEqual(summary['recorded_llm_requests'], 5)
            self.assertEqual(summary['finished'], 5)

    async def test_selection_deduplicates_and_preserves_all_references(self):
        with TemporaryDirectory(dir=batch.ROOT / 'data/trend_data/images') as temporary:
            source = self.fixture(temporary)
            selected, stats = batch.select_images(source, 2)
            self.assertEqual(len(selected), 2)
            self.assertEqual(len(selected[0]['references']), 2)
            self.assertEqual(stats['image_references'], 8)
            self.assertEqual(stats['unique_downloaded_images'], 7)
            with self.assertRaises(ValueError):
                batch.select_images(source, 1001)

    async def test_unknown_submission_is_recorded_and_never_reissued(self):
        with TemporaryDirectory(dir=batch.ROOT / 'data/trend_data/images') as temporary:
            source = self.fixture(temporary)
            folder = Path(temporary) / 'batch'
            batch.prepare(source, folder, limit=1)
            (folder / 'calls/I0001.json').write_text(json.dumps({'state': 'submitted', 'image_id': 'fixture_0'}))
            with patch.object(batch.quality, 'classify') as caller:
                await batch.execute(folder)
                caller.assert_not_called()
            summary = json.loads((folder / 'summary.json').read_text())
            self.assertEqual(summary['counts']['execution_unknown'], 1)
            self.assertEqual(summary['unknown_submission_states'], 1)

    async def test_remaining_mode_excludes_old_failures_and_keeps_same_configuration(self):
        with TemporaryDirectory(dir=batch.ROOT / 'data/trend_data/images') as temporary:
            source = self.fixture(temporary)
            previous = Path(temporary) / 'previous'
            batch.prepare(source, previous, limit=2)
            manifest = json.loads((previous / 'manifest.json').read_text())
            records = {}
            for index, item in enumerate(manifest['entries']):
                record = {'state': 'finished', 'status': 'execution_error' if index == 0 else 'complete',
                          'decision': None if index == 0 else 'PASS', 'usage': {'llm_request_count': 1}}
                records[item['entry_id']] = record
                batch.save(previous / 'calls' / (item['entry_id'] + '.json'), record)
            batch.export(previous, manifest, records, status='completed', started_at='fixture', max_active=2)
            remaining = Path(temporary) / 'remaining'
            batch.prepare(source, remaining, remaining_after=previous)
            result = json.loads((remaining / 'manifest.json').read_text())
            old_hashes = {item['image_sha256'] for item in manifest['entries']}
            new_hashes = {item['image_sha256'] for item in result['entries']}
            self.assertEqual(result['selected_count'], 5)
            self.assertEqual(result['max_requests'], 5)
            self.assertFalse(old_hashes & new_hashes)
            self.assertEqual(result['parameters'], manifest['parameters'])
            self.assertEqual(result['prompt_sha256'], manifest['prompt_sha256'])
            self.assertEqual(result['population']['excluded_unique_images'], 2)
            with self.assertRaises(ValueError):
                batch.prepare(source, Path(temporary) / 'changed_model', model='gemini-3.8-flash', remaining_after=previous)

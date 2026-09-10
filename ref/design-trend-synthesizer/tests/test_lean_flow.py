"""同一极小代表夹具验证直出、分包和调用预算；适配器为假实现，不调用真实模型。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import lean
import pipeline
import test_lean_input as sample


class LeanFlowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = sample.LeanInputTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def args(self, **changes):
        data = dict(trends=str(self.fixture.trend_path), users=str(self.fixture.user_path),
                    project_root=str(self.root), output=str(self.root/'run'), start_date='2026-01-01',
                    end_date='2026-01-31', undated='exclude', user_limit=None, batch_chars=48000,
                    max_calls=12, map_output_tokens=2500, final_output_tokens=5000,
                    model=None, model_parameters='{}', no_cache=False, dry_run=False)
        data.update(changes)
        return SimpleNamespace(**data)

    def multi_args(self, **changes):
        # 两条不到千字的资料足以触发分包，无需真实大数据验证流程。
        for row in self.fixture.trends['trends']:
            row['summary_zh'] = '保留柔和触感和明确轮廓。' * 42
        self.fixture.save_inputs()
        return self.args(batch_chars=2000, **changes)

    @staticmethod
    def fake_adapter(command, request_path, result_path):
        request = lean.read(request_path)
        refs = list(request['aliases']) if request['aliases'] else request['source_ids']
        text = '## 柔和表面与轮廓\n可以探索不同材质的触感和外形。['+' '.join(refs)+']'
        lean.write(result_path, {'status':'ok', 'raw_response':text, 'model':'offline-fixture',
                                'input_tokens':123, 'output_tokens':45})
        return None

    def test_small_data_direct_and_free_prose_do_not_require_json(self):
        manifest = lean.prepare(self.args())
        self.assertEqual(manifest['plan']['planned_calls'], 1)
        self.assertTrue(manifest['plan']['direct'])
        jid = lean.next_job(manifest['run_dir'])['pending'][0]
        result = lean.accept(manifest['run_dir'], jid, '可以探索低反光表面。[T00001 U000001]', 'host-fixture')
        self.assertTrue(result['completion']['has_content'])
        self.assertEqual(result['completion']['trends'], 1)
        self.assertEqual(result['calls'], 0)
        self.assertEqual(lean.read(Path(manifest['run_dir'])/'performance_report.json')['manual_host_jobs'], 1)
        self.assertFalse(lean.next_job(manifest['run_dir'])['pending'])

    def test_optional_output_budget_is_omitted_for_map_and_final(self):
        manifest = lean.prepare(self.multi_args(model='offline-fixture', map_output_tokens=None,
                                               final_output_tokens=None))
        self.assertIsNone(manifest['plan']['planned_output_token_cap'])
        run = Path(manifest['run_dir'])
        for jid in lean.status(run)['pending']:
            job = lean.read(run/'requests'/f'{jid}.json')
            self.assertNotIn('max_tokens', job['model_profile']['parameters'])
            lean.accept(run, jid, '## 柔和表面\n触感与轮廓。['+' '.join(job['source_ids'])+']')
        jid = lean.next_job(run)['pending'][0]
        final = lean.read(run/'requests'/f'{jid}.json')
        self.assertNotIn('max_tokens', final['model_profile']['parameters'])

    def test_large_path_is_map_then_single_final_with_short_notes(self):
        manifest = lean.prepare(self.multi_args())
        self.assertFalse(manifest['plan']['direct'])
        run = Path(manifest['run_dir'])
        for jid in lean.status(run)['pending']:
            request = lean.read(run/'requests'/f'{jid}.json')
            lean.accept(run, jid, '## 表面与触感\n保持不同偏好的选择。['+' '.join(request['source_ids'])+']')
        final = lean.next_job(run)['pending']
        self.assertEqual(len(final), 1)
        request = lean.read(run/'requests'/f'{final[0]}.json')
        self.assertTrue(request['aliases'])
        self.assertNotIn(self.fixture.answer, request['messages'][1]['content'])
        self.assertLessEqual(lean.message_chars(request['messages']), 2000)
        result = lean.accept(run, final[0], '## 触感设计\n可以结合表面与轮廓。['+' '.join(request['aliases'])+']')
        self.assertEqual(result['completion']['trends'], 1)
        self.assertEqual(len(list((run/'requests').glob('synthesize-*.json'))), 1)

    def test_planned_calls_reject_excess_before_writing_or_calling(self):
        with self.assertRaisesRegex(ValueError, '超过max-calls'):
            lean.prepare(self.multi_args(max_calls=1))
        self.assertFalse((self.root/'run').exists())

    def test_script_advances_once_and_cache_saves_digest_calls(self):
        first = lean.prepare(self.multi_args(model='offline-fixture'))
        with patch('runner.invoke_adapter', self.fake_adapter):
            result = lean.run_models(first['run_dir'], ['offline-fixture'])
        self.assertTrue(result['completion']['has_content'])
        self.assertEqual(result['calls'], first['plan']['planned_calls'])
        # 同一微型输入重用笔记缓存；只需最后一次综合，旧调用用量不计入本轮。
        second = lean.prepare(self.args(batch_chars=2000, model='offline-fixture', output=str(self.root/'second')))
        with patch('runner.invoke_adapter', self.fake_adapter):
            replay = lean.run_models(second['run_dir'], ['offline-fixture'])
            again = lean.run_models(second['run_dir'], ['offline-fixture'])
        self.assertEqual(replay['calls'], 1)
        self.assertEqual(again['calls'], 1)
        perf = lean.performance(second['run_dir'])
        self.assertEqual(perf['input_tokens_known'], 123)
        self.assertEqual(perf['cache_hits'], second['plan']['map_jobs'])

    def test_service_deferral_and_total_call_cap_survive_resume(self):
        options = self.multi_args(model='offline-fixture', max_calls=3)
        preview = lean.prepare(self.multi_args(model='offline-fixture', max_calls=12, dry_run=True))
        options.max_calls = preview['plan']['planned_calls']
        manifest = lean.prepare(options); run = Path(manifest['run_dir'])
        def overloaded(command, request, result):
            lean.write(result, {'status':'error', 'category':'overload', 'retry_after_seconds':60})
        with patch('runner.invoke_adapter', overloaded):
            stopped = lean.run_models(run, ['offline-fixture'])
            immediate = lean.run_models(run, ['offline-fixture'])
        self.assertEqual(stopped['status'], 'deferred')
        self.assertEqual(immediate['calls'], 1)
        state = lean.read(run/'state.json')
        state['jobs'][stopped['pending'][0]]['ready_at'] = 0  # 模拟等待已经结束，测试不实际休眠。
        lean.write(run/'state.json', state)
        with patch('runner.invoke_adapter', self.fake_adapter):
            result = lean.run_models(run, ['offline-fixture'])
        self.assertLessEqual(result['calls'], options.max_calls)
        self.assertTrue(result['failed'])
        self.assertTrue(result['completion']['partial'])

    def test_empty_final_is_empty_and_public_entrypoint_uses_lean(self):
        with patch('lean.main', return_value=0) as route:
            self.assertEqual(pipeline.main(['prepare', '--dry-run']), 0)
        route.assert_called_once_with(['prepare','--dry-run'])
        manifest = lean.prepare(self.args())
        jid = lean.status(manifest['run_dir'])['pending'][0]
        result = lean.accept(manifest['run_dir'], jid, '')
        self.assertEqual(result['completion']['status'], 'empty')
        self.assertFalse(result['completion']['has_content'])
        failed = lean.prepare(self.args(output=str(self.root/'failed-final')))
        run = Path(failed['run_dir']); state = lean.read(run/'state.json')
        for job in state['jobs'].values(): job['status'] = 'failed'
        lean.write(run/'state.json', state)
        stopped = lean.next_job(run)
        self.assertEqual(stopped['completion']['status'], 'empty')


if __name__ == '__main__':
    unittest.main()

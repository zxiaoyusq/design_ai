"""双模型实测账本的离线边界测试，不触发模型请求。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import importlib.util


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_trend_quality_benchmark.py'
spec = importlib.util.spec_from_file_location('trend_quality_benchmark', SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class TrendQualityBenchmarkTests(TestCase):
    def test_internal_model_loop_is_blocked_before_second_submission(self):
        telemetry = benchmark.OneRequestTelemetry()
        telemetry.on_chat_model_start({}, [], run_id=None)
        with self.assertRaises(RuntimeError):
            telemetry.on_chat_model_start({}, [], run_id=None)
        self.assertEqual(telemetry.snapshot()['llm_request_count'], 1)

    def test_failed_latency_is_not_reported_as_successful_latency(self):
        usage = {'llm_request_count': 1, 'input_tokens': 0, 'output_tokens': 0,
                 'total_tokens': 0, 'requests_with_usage': 0}
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            result = benchmark.summarize(folder, {'sample': []}, {
                'started_at': 'start', 'finished_at': 'end', 'rows': [
                    {'sample_id': 'S01', 'model': benchmark.MODELS[0], 'duration_seconds': 2.0,
                     'attempts': [{'duration_seconds': 2.0, 'usage': usage}],
                     'resolved': {'status': 'execution_error', 'decision': None}},
                    {'sample_id': 'S02', 'model': benchmark.MODELS[0], 'duration_seconds': 20.0,
                     'attempts': [{'duration_seconds': 20.0, 'usage': usage}],
                     'resolved': {'status': 'complete', 'decision': 'PASS'}},
                ],
            })
            model = result['models'][benchmark.MODELS[0]]
            self.assertEqual(model['complete_mean_seconds'], 20.0)
            self.assertEqual(model['execution_error_mean_seconds'], 2.0)
            self.assertFalse(model['usage_covers_all_submissions'])
            self.assertEqual(model['results'], {'execution_error': 1, 'PASS': 1})

    def test_unknown_or_missing_pairs_do_not_count_as_disagreements(self):
        with TemporaryDirectory() as temporary:
            result = benchmark.summarize(Path(temporary), {
                'sample': [{'sample_id': 'S01', 'image_id': 'test',
                            'source_path': 'fixture', 'snapshot': 'fixture.png'}],
            }, {'started_at': 'start', 'finished_at': 'end', 'rows': []})
            self.assertEqual(result['sample_count'], 1)
            self.assertEqual(result['comparable_pairs'], 0)
            self.assertEqual(result['decision_disagreements'], 0)

    def test_comparison_latency_uses_same_successful_images(self):
        usage = {'llm_request_count': 1, 'input_tokens': 10, 'output_tokens': 10,
                 'total_tokens': 20, 'requests_with_usage': 1}
        rows = []
        for sample, model, duration in [('S01', benchmark.MODELS[0], 10.0),
                                        ('S01', benchmark.MODELS[1], 20.0),
                                        ('S02', benchmark.MODELS[1], 100.0)]:
            rows.append({'sample_id': sample, 'model': model, 'duration_seconds': duration,
                         'attempts': [{'duration_seconds': duration, 'usage': usage}],
                         'resolved': {'status': 'complete', 'decision': 'PASS'}})
        sample = [{'sample_id': name, 'image_id': name, 'source_path': 'fixture',
                   'snapshot': 'fixture.png'} for name in ('S01', 'S02')]
        with TemporaryDirectory() as temporary:
            summary = benchmark.summarize(Path(temporary), {'sample': sample}, {
                'started_at': 'start', 'finished_at': 'end', 'rows': rows,
            })
        self.assertEqual(summary['models'][benchmark.MODELS[1]]['complete_mean_seconds'], 60.0)
        self.assertEqual(summary['models'][benchmark.MODELS[1]]['paired_complete_mean_seconds'], 20.0)
        self.assertEqual(summary['comparable_pairs'], 1)
        self.assertEqual(summary['decision_agreements'], 1)

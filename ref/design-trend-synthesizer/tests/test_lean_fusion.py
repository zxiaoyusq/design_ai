"""离线核对聚合握手的冻结范围、原角色、关系旁表和旧运行兼容。"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import lean
import lean_input
import lean_output
import test_lean_flow as fixture


class LeanFusionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.LeanFlowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        args = self.fixture.args()
        self.bundle = lean_input.build_sources(args.trends, args.users, self.root,
                                              args.start_date, args.end_date)
        self.bundle['upstream_selection'] = {'trend_output_id': 'theme-run', 'research_output_id': 'user-run'}
        self.bundle['input_snapshots'] = {
            key: {**entry, 'content': Path(entry['path']).read_text(encoding='utf-8')}
            for key, entry in self.bundle['inputs'].items()}

    def test_bundle_freezes_exact_inputs_without_reading_default_libraries(self):
        self.bundle['sources']['U000001']['semantic_context'] = {
            'sourceRole': 'analysis_note', 'originalAnswer': '只在这个对象上适用。',
            'conditions': ['不推广到所有场景'], 'attitudes': [{'emotion': 'DISLIKE'}]}
        with patch('lean.build_sources', side_effect=AssertionError('must not read raw library')):
            manifest = lean.prepare(self.fixture.args(), source_data=self.bundle)
        run = Path(manifest['run_dir'])
        self.assertNotIn('input_snapshots', manifest)
        for key, entry in manifest['inputs'].items():
            frozen = Path(entry['path']).read_bytes()
            self.assertEqual(hashlib.sha256(frozen).hexdigest(), entry['sha256'])
            self.assertEqual(frozen.decode(), self.bundle['input_snapshots'][key]['content'])
            self.assertEqual(entry['original_path'], self.bundle['inputs'][key]['path'])
        request = lean.read(run / 'requests' / 'synthesize-001.json')
        self.assertIn('analysis_note', request['messages'][1]['content'])
        self.assertIn('DISLIKE', request['messages'][1]['content'])
        self.assertNotIn('image_refs', request['messages'][1]['content'])
        self.assertEqual(lean.read(run / 'sources.json'), self.bundle['sources'])
        # 保存快照不能反向修改应用的输入对象。
        self.assertEqual(self.bundle['inputs']['trends']['path'], str(self.fixture.fixture.trend_path))

    def test_corrupt_snapshot_fails_before_creating_run(self):
        self.bundle['input_snapshots']['trends']['content'] += ' '
        with self.assertRaisesRegex(ValueError, 'SHA不一致'):
            lean.prepare(self.fixture.args(), source_data=self.bundle)
        self.assertFalse((self.root / 'run').exists())

    def test_model_subset_preserves_unread_members_and_associated_images(self):
        sources = self.bundle['sources']
        member = copy.deepcopy(sources['T00001'])
        member['semantic_context'] = {'upstream_output_id': 'theme-run', 'memberships': [
            {'theme_id': 'theme-1', 'title': '连续轮廓', 'definition': '相同父主题'}]}
        sources['T00001'] = member
        theme = copy.deepcopy(member)
        theme.update(id='theme:one', source_id='upstream_theme:theme-1', image_refs=[])
        theme['fields'] = {'title_zh': '连续轮廓', 'summary_zh': '现成主题摘要'}
        theme['semantic_context']['source_role'] = 'analysis_note'
        sources['T99999'] = theme
        sources['T00001']['fields']['summary_zh'] = '未读完整成员原文' * 5000
        self.bundle['model_source_ids'] = ['T99999', 'U000001']
        self.bundle['model_input_scope'] = {'scope': 'theme summaries and selected user sources', 'all_members_read': False}
        manifest = lean.prepare(self.fixture.args(), source_data=self.bundle)
        run = Path(manifest['run_dir'])
        request = lean.read(run / 'requests' / 'synthesize-001.json')
        self.assertEqual(request['source_ids'], ['T99999', 'U000001'])
        self.assertNotIn('未读完整成员原文', request['messages'][1]['content'])
        text = ('## 连续轮廓\n可探索连续表面。[T99999 U000001]\n'
                '依据类型：anchored_extension\n共同原则：减少分割。\n'
                '适用边界：原对象条件待确认。\n反向与未决：未读全部成员。')
        lean.accept(run, 'synthesize-001', text, 'offline-model')
        output = lean.read(run / 'high_potential_trends.json')
        card = output['trends'][0]
        self.assertEqual(card['relation_basis'], 'anchored_extension')
        self.assertEqual(card['evidence_review_status'], 'not_reviewed')
        self.assertIn('trend:', card['associated_source_records'][0]['record_id'])
        self.assertEqual(card['associated_source_records'][0]['association_type'], 'same_cluster_association')
        self.assertTrue(all(ref['association_type'] == 'same_cluster_association' for ref in card['associated_image_refs']))
        self.assertEqual(card['source_records'][0]['semantic_context']['source_role'], 'analysis_note')
        self.assertEqual(output['model_input_scope'], self.bundle['model_input_scope'])
        handoff = lean.read(run / 'handoff.json')
        self.assertEqual(handoff['execution']['model'], 'offline-model')
        self.assertEqual(handoff['model_input_scope'], self.bundle['model_input_scope'])
        self.assertEqual(lean.read(run / 'sources.json')['T00001']['fields']['summary_zh'],
                         sources['T00001']['fields']['summary_zh'])

    def test_missing_labels_remain_unknown_without_repair_or_false_review(self):
        manifest = lean.prepare(self.fixture.args(), source_data=self.bundle)
        run = Path(manifest['run_dir'])
        result = lean.accept(run, 'synthesize-001', '## 低反光表面\n可探索。[T00001 U000001]', 'offline-model')
        card = lean.read(run / 'high_potential_trends.json')['trends'][0]
        self.assertEqual(card['relation_basis'], 'unknown')
        self.assertEqual(card['evidence_review_status'], 'not_reviewed')
        self.assertEqual(result['calls'], 0)
        self.assertFalse(result['pending'])
        self.assertTrue(any('依据或边界' in item for item in result['completion']['warnings']))

    def test_shared_theme_definitions_pack_once_and_missing_images_keep_identity(self):
        source = copy.deepcopy(self.bundle['sources']['T00001'])
        source['semantic_context'] = {'memberships': [{'theme_id': 't1', 'title': '唯一主题定义',
                                                     'definition': '共同定义', 'membership': {'role': 'member'}}]}
        second = copy.deepcopy(source)
        second['id'] = 'trend:second'
        payload = json.loads(lean_input.pack_sources({'T00001': source, 'T00002': second}, 48000)[0]['text'])
        self.assertEqual(len(payload['semantic_catalog']), 1)
        self.assertEqual(payload['trends'][0]['semantic_context']['memberships'][0]['definition_ref'],
                         payload['trends'][1]['semantic_context']['memberships'][0]['definition_ref'])
        path = self.root / 'shared-image.jpg'
        path.write_bytes(b'original bytes')
        cache = {}
        with patch.object(lean_output.hashlib, 'file_digest', wraps=hashlib.file_digest) as calculate:
            one = lean_output._image_identity(path, cache)
            two = lean_output._image_identity(path, cache)
        self.assertEqual(calculate.call_count, 1)
        self.assertEqual(one['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(one, two)
        self.assertEqual(lean_output._image_identity(self.root / 'missing.jpg', cache)['identity_status'], 'missing')

    def test_existing_theme_summaries_share_a_call_without_losing_theme_identity(self):
        records = {}
        for i in range(3):
            record = copy.deepcopy(self.bundle['sources']['T00001'])
            record['id'] = f'theme:{i}'
            record['clustering_label'] = f'主题{i}'
            record['semantic_context'] = {'input_text_kind': 'upstream_summary',
                                          'memberships': [{'theme_id': str(i), 'definition': f'定义{i}'}]}
            records[f'T{i:05}'] = record
        packs = lean_input.pack_sources(records, 48000)
        self.assertEqual(len(packs), 1)
        payload = json.loads(packs[0]['text'])
        self.assertEqual(payload['input_mode'], 'upstream_theme_summaries')
        self.assertEqual([row['clustering_label'] for row in payload['trends']], ['主题0', '主题1', '主题2'])
        self.assertEqual(len(payload['semantic_catalog']), 3)

    def prepare_digest_scope(self):
        sources = self.bundle['sources']
        sources['T00001']['fields']['summary_zh'] = '已有主题完整定义。' * 600
        sources['T00001']['semantic_context'] = {'input_text_kind': 'upstream_summary',
            'source_role': 'analysis_note', 'original_object': '原场景对象'}
        sources['U000001']['fields']['ai_analysis'] = '用于使微型夹具分包的回答。' * 450
        sources['U000001']['semantic_context'] = {'sourceRole': 'respondent_answer',
            'answer_type': 'translated', 'source_language': 'en', 'originalAnswer': 'Original exact text'}
        self.bundle['model_source_ids'] = ['T00001', 'U000001']
        self.bundle['model_input_scope'] = {'mode': 'existing_theme_handshake', 'trend_theme_count': 1,
            'full_member_articles_archived': 2, 'research_records_read': 1,
            'full_member_articles_reread': False}
        manifest = lean.prepare(self.fixture.args(batch_chars=9000), source_data=self.bundle)
        self.assertFalse(manifest['plan']['direct'])
        return Path(manifest['run_dir'])

    def test_final_keeps_tail_constraints_and_deduplicated_original_roles(self):
        run = self.prepare_digest_scope()
        for jid in lean.status(run)['pending']:
            job = lean.read(run / 'requests' / f'{jid}.json')
            lean.accept(run, jid, '## 连续关系\n' + '摘要冗长部分。' * 120 +
                '\n依据类型：anchored_extension\n共同原则：保持原始关系。\n'
                '适用边界：尾部条件不能丢失。\n反向与未决：尾部反向仍未核对。[' +
                ' '.join(job['source_ids']) + ']')
        jid = lean.next_job(run)['pending'][0]
        job = lean.read(run / 'requests' / f'{jid}.json')
        payload = json.loads(job['messages'][1]['content'])
        self.assertEqual(payload['model_input_scope'], self.bundle['model_input_scope'])
        self.assertTrue(all('尾部条件不能丢失' in row['conditions_and_limits'] for row in payload['notes']))
        self.assertTrue(all('尾部反向仍未核对' in row['unresolved_questions'] for row in payload['notes']))
        self.assertTrue(all('尾部条件不能丢失' not in row['summary'] for row in payload['notes']))
        contexts = list(payload['source_contexts'].values())
        self.assertTrue(any(row.get('source_role') == 'analysis_note' and
                            row.get('input_text_kind') == 'upstream_summary' for row in contexts))
        self.assertTrue(any(row.get('sourceRole') == 'respondent_answer' and
                            row.get('answer_type') == 'translated' for row in contexts))
        self.assertNotIn('Original exact text', job['messages'][1]['content'])
        self.assertLessEqual(lean.message_chars(job['messages']), 9000)
        lean.accept(run, jid, '## 连续关系\n可探索。[N0001 N0002]')
        report = (run / 'report.md').read_text()
        self.assertIn('读取 1 个既有趋势主题', report)
        self.assertIn('关联归档成员文章 2 篇', report)
        self.assertIn('本轮未逐篇复读', report)

    def test_constraint_overflow_stops_without_truncating_or_new_calls(self):
        run = self.prepare_digest_scope()
        for jid in lean.status(run)['pending']:
            job = lean.read(run / 'requests' / f'{jid}.json')
            lean.accept(run, jid, '## 连续关系\n有限摘要。\n适用边界：' + '必须保留' * 2500 +
                        '\n反向与未决：未核对。[' + ' '.join(job['source_ids']) + ']')
        with self.assertRaisesRegex(ValueError, '不截断约束或自动扩展调用'):
            lean.next_job(run)
        self.assertFalse(list((run / 'requests').glob('synthesize-*.json')))
        self.assertEqual(lean.status(run)['calls'], 0)
        self.assertIn('必须保留' * 2500, lean.read(run / 'notes.json')[0]['text'])

    def test_old_final_rows_keep_legacy_shape(self):
        run = self.prepare_digest_scope()
        manifest = lean.read(run / 'manifest.json')
        manifest['skill_version'] = '3.3.1'
        lean.write(run / 'manifest.json', manifest)
        for jid in lean.status(run)['pending']:
            job = lean.read(run / 'requests' / f'{jid}.json')
            lean.accept(run, jid, '## 旧方向\n旧笔记。[ ' + ' '.join(job['source_ids']) +
                        ']\n适用边界：原条件。')
        jid = lean.next_job(run)['pending'][0]
        job = lean.read(run / 'requests' / f'{jid}.json')
        payload = json.loads(job['messages'][1]['content'])
        self.assertNotIn('source_contexts', payload)
        self.assertNotIn('model_input_scope', payload)
        self.assertTrue(all('conditions_and_limits' not in row for row in payload['notes']))
        self.assertEqual(job['prompt_version'], '3.3.1:synthesize')

    def test_old_run_prompt_identity_does_not_change_on_resume(self):
        from lean_prompts_v33 import FINAL_PROMPT
        manifest = lean.prepare(self.fixture.args(dry_run=True), source_data=self.bundle)
        manifest['skill_version'] = '3.3.1'
        job = lean.make_job(self.root / 'legacy', 'synthesize', '001', '旧运行笔记', [], manifest)
        self.assertEqual(job['messages'][0]['content'], FINAL_PROMPT)
        self.assertEqual(job['prompt_version'], '3.3.1:synthesize')


if __name__ == '__main__':
    unittest.main()

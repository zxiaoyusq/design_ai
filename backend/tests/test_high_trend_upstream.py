"""离线验证模块输出交接；使用小型固定资料，不请求模型。"""
import hashlib
import json
from pathlib import Path

import pytest

from app.services.high_trends.upstream import build_source_data, list_inputs
from app.services.user_research.storage import ResearchStore

TID = 'a' * 32
UID = 'import_' + 'b' * 32


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


@pytest.fixture
def upstream(tmp_path):
    task = tmp_path / 'data/result/article_trend_clustering' / TID
    records = [dict(article_id=str(i), title=f'完整标题{i}', summary='完整摘要' * 30,
                    text_kind='source_paraphrase', source_group_id=f'g{i}', published_at='2026-10-21') for i in range(10)]
    members = [dict(article_id=str(i), theme_id='theme1', role='primary', status='supported',
                    anchor='完整摘要', reason='保留完整表面差异') for i in range(10)]
    result = dict(trends=[dict(theme_id='theme1', title='异质表面对照', definition='表面差异构成层次',
                              boundary='不可只按材料名称推断', members=members,
                              secondary_members=[], reviews=members)], records=records)
    write(task / 'task.json', dict(id=TID, status='completed', created_at='2026-10-21', model_id='test', article_count=10))
    write(task / 'result.json', result)
    write(task / 'records.json', records)
    image = tmp_path / 'data/trend_data/images/t.jpg'
    image.parent.mkdir(parents=True)
    image.write_bytes(b'trend')
    write(tmp_path / 'data/trend_data/trend_info_0930/trends.json', {'trends': [
        {'id': str(i), 'images': [{'image_id': f't{i}', 'local_path': '../images/t.jpg', 'status': 'downloaded'}]} for i in range(10)]})
    run = tmp_path / 'data/result/user_research_intake' / UID[7:]
    positive, negative = run / 'assets/yes.png', run / 'assets/no.png'
    positive.parent.mkdir(parents=True)
    positive.write_bytes(b'yes'); negative.write_bytes(b'no')
    write(run / 'user.json', dict(id=UID, name='完整用户', status='ready', createdAt='2026-10-21', profile={}, warnings=[],
        provenance={'sourceLanguage': 'en'},
        records=[dict(id='q1', question='偏好及边界', answer='喜欢纹理但不喜欢强反光。', originalAnswer='Texture, without strong glare.',
                      sourceRole='participant', sourceSlide=3, sourceFile='test.pptx', section='颜色', imageIds=['yes', 'no'])],
        images=[dict(id='yes', code='A', emotion='ENJOY', status='extracted'),
                dict(id='no', code='B', emotion='DISLIKE', status='extracted')]))
    write(run / 'assets.json', {'yes': str(positive), 'no': str(negative)})
    return tmp_path


def test_full_module_outputs_and_original_language_are_frozen(upstream):
    listing = list_inputs(upstream)
    assert listing['research_outputs'][0]['selectable'] is True
    data = build_source_data(upstream, [UID], 'task:' + TID)
    assert data['counts']['trend_records'] == 10  # 不使用页面最多八条代表证据。
    assert data['selection']['mode'] == 'module_outputs'
    assert data['model_source_ids'] == ['T00011', 'U000001']
    assert data['trend_categories'][0]['source_ids'] == ['T00011']
    assert data['trend_categories'][0]['article_count'] == 10
    assert data['counts']['model_trend_records'] == data['counts']['trend_cluster_count'] == 1
    assert data['model_input_scope']['full_member_articles_reread'] is False
    summary = data['sources']['T00011']
    assert summary['image_refs'] == []
    assert summary['semantic_context']['input_text_kind'] == 'upstream_summary'
    assert len(summary['semantic_context']['representative_anchors']) == 3
    assert summary['json_pointer'] == '/trends/0'
    user = data['sources']['U000001']
    assert user['fields']['ai_analysis'] == '喜欢纹理但不喜欢强反光。'
    assert user['semantic_context']['originalAnswer'] == 'Texture, without strong glare.'
    assert user['semantic_context']['sourceRole'] == 'participant'
    assert [a['emotion'] for a in user['semantic_context']['attitudes']] == ['ENJOY', 'DISLIKE']
    assert len(user['image_refs']) == len(data['user_image_inventory']) == 1
    assert user['image_refs'][0]['emotion_tag'] == 'ENJOY'
    for source in data['sources'].values():
        snapshot = data['input_snapshots'][source['source_file']]
        assert hashlib.sha256(snapshot['content'].encode()).hexdigest() == snapshot['sha256']
        document = json.loads(snapshot['content'])
        for component in source['json_pointer'].strip('/').split('/'):
            document = document[int(component)] if isinstance(document, list) else document[component]
        assert isinstance(document, dict)
    trend = data['sources']['T00010']
    assert len(trend['fields']['summary_zh']) == 120
    assert trend['semantic_context']['memberships'][0]['membership']['role'] == 'primary'
    assert trend['semantic_context']['memberships'][0]['boundary'] == '不可只按材料名称推断'


def test_pending_research_disabled_and_invalid_identity_rejected(upstream):
    path = upstream / 'data/result/user_research_intake' / UID[7:] / 'user.json'
    document = json.loads(path.read_text()); document['status'] = 'needs_review'; write(path, document)
    assert list_inputs(upstream)['research_outputs'][0]['selectable'] is False
    with pytest.raises(ValueError, match='未确认'):
        build_source_data(upstream, [UID], 'task:' + TID)
    document['status'] = 'ready'; write(path, document)
    with pytest.raises(ValueError, match='标识无效'):
        build_source_data(upstream, [UID], 'task:../../secret')
    with pytest.raises(ValueError, match='不能重复'):
        build_source_data(upstream, [UID, UID], 'task:' + TID)


def test_broken_result_disabled_without_raw_catalog_fallback(upstream):
    result = upstream / 'data/result/article_trend_clustering' / TID / 'result.json'
    result.unlink()
    assert list_inputs(upstream)['trend_outputs'][0]['selectable'] is False
    with pytest.raises(FileNotFoundError):
        build_source_data(upstream, [UID], 'task:' + TID)


def test_outside_image_path_is_rejected(upstream):
    path = upstream / 'data/trend_data/trend_info_0930/trends.json'
    write(path, {'trends': [{'id': '0', 'images': [{'local_path': '../../../outside.jpg'}]}]})
    with pytest.raises(ValueError, match='允许的素材目录'):
        build_source_data(upstream, [UID], 'task:' + TID)


def test_changed_frozen_article_records_rejected(upstream):
    path = upstream / 'data/result/article_trend_clustering' / TID / 'records.json'
    records = json.loads(path.read_text()); records[0]['summary'] = '后来改过的文本'; write(path, records)
    assert not list_inputs(upstream)['trend_outputs'][0]['selectable']
    with pytest.raises(ValueError, match='不一致'):
        build_source_data(upstream, [UID], 'task:' + TID)


def test_legacy_full_members_preserve_pending_review(upstream):
    history = upstream / 'data/result/trend_text_clusters/astra_consensus_20261001/final'
    articles, evidence, points = [], [], []
    for i in range(10):
        sid = f'T:{i}'
        articles.append(dict(source_id=sid, original_id=str(i), metadata={}, source_group_id=f'g{i}'))
        evidence += [dict(source_id=sid, field='title_zh', text=f'旧标题{i}'),
                     dict(source_id=sid, field='summary_zh', text=f'旧完整摘要{i}')]
        points.append(dict(point_id=f'p{i}', evidence_id=sid + ':summary_zh', quote=f'旧完整摘要{i}', condition='仅在局部'))
    write(history / 'trend-catalogue.json', dict(articles=articles, evidence=evidence))
    write(history / 'trend-clusters.json', dict(review_status='pending_human_review', clusters=[
        dict(cluster_id='GT-1', title='连续曲面', definition='保持连续性', point_ids=[p['point_id'] for p in points],
             boundaries={'excludes': ['不可外推到全部对象']}, lineage=[{'members': points}])]))
    write(history / 'summary.json', dict(articles=10))
    write(history / 'execution.json', dict(compiled_at='2026-10-01', selection_analysis={'model_id': 'astra'}))
    data = build_source_data(upstream, [UID], 'history:astra-consensus-20261001')
    assert data['counts']['trend_records'] == 10
    assert data['sources']['T00010']['fields']['summary_zh'] == '旧完整摘要9'
    assert data['model_source_ids'] == ['T00011', 'U000001']
    assert data['trend_categories'][0]['source_ids'] == ['T00011']
    assert data['trend_categories'][0]['article_count'] == 10
    summary = data['sources']['T00011']
    assert summary['json_pointer'] == '/clusters/0'
    assert summary['semantic_context']['memberships'][0]['cluster_id'] == 'GT-1'
    assert len(summary['semantic_context']['representative_anchors']) == 3
    assert summary['image_refs'] == []
    context = data['sources']['T00010']['semantic_context']['memberships'][0]
    assert context['review_status'] == 'pending_human_review'
    assert context['points'][0]['condition'] == '仅在局部'
    assert any('待人工审阅' in w for w in data['warnings'])


def test_seed_uses_registered_ppt_output_without_old_analysis(upstream):
    path = upstream / 'data/userreseach_data/users_selected_5.json'
    write(path, {'users': [dict(id='75', profile={}, name='已登记用户', ppt_supplement={}, ppt_images=[],
        aesthetic_research=[dict(id='old-analysis', ai_analysis='旧分析不能混成原话'),
                            dict(id='ppt-one', question='完整问题', ai_analysis='PPT完整翻译回答', source_type='ppt_supplement',
                                 source_language='en', source_slide=4, answer_type='用户原始填写（PPT翻译补录）')],
        demand_research=[], image_preferences=[])]})
    data = build_source_data(upstream, ['75'], 'task:' + TID)
    users = [s for s in data['sources'].values() if s['kind'] != 'trend']
    assert len(users) == 1
    assert users[0]['fields']['ai_analysis'] == 'PPT完整翻译回答'
    assert users[0]['json_pointer'] == '/users/0/aesthetic_research/1'
    assert users[0]['semantic_context']['source_slide'] == 4
    assert users[0]['semantic_context']['originalAnswer'] is None
    assert '翻译补录' in users[0]['semantic_context']['answer_type']

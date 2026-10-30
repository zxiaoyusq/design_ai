"""把两个网页模块的已登记完整结果冻结为高潜输入，不从展示卡片反推原文。"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from app.services.article_trends.history import HISTORY_ID, HISTORY_PATH, LEGACY_NOTICE
from app.services.user_research.storage import ResearchStore

TASK_ID = re.compile(r"[a-f0-9]{32}\Z")
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.avif'}


def _read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _store(root):
    return ResearchStore(root / 'data/result/user_research_intake',
                         root / 'data/userreseach_data/users_selected_5.json',
                         root / 'data/userreseach_data')


def _registered_users(root, store):
    """逐用户容错，损坏的上传结果仍显示为不可选，不遮住其他已完成资料。"""
    ids = []
    if store.seed_file.is_file():
        try:
            ids.extend(str(u['id']) for u in _read(store.seed_file)['users'])
        except (OSError, ValueError, KeyError, TypeError):
            yield dict(id='seed-unavailable', title='既有用研资料不可用', status='unavailable',
                       selectable=False, user_count=0, record_count=0, created_at=None,
                       warnings=['已登记用研资料损坏，不能使用。'])
    if store.root.exists():
        ids.extend('import_' + p.parent.name for p in sorted(store.root.glob('*/user.json'))
                   if TASK_ID.fullmatch(p.parent.name))
    for uid in dict.fromkeys(ids):
        try:
            value = store.get_user(uid)
            rows = value['records']
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ValueError('回答记录格式异常')
            valid = value.get('status') == 'ready' and bool(rows)
            warnings = list(value.get('warnings', []))
            if value.get('status') != 'ready':
                warnings.append('请先在用研聚合模块完成确认。')
            if not rows:
                warnings.append('没有可用的完整回答。')
            yield dict(id=uid, title=value.get('name') or uid, status=value.get('status', 'unavailable'),
                       selectable=valid, user_count=1, record_count=len(rows),
                       created_at=value.get('createdAt'), warnings=warnings)
        except (OSError, ValueError, KeyError, TypeError):
            yield dict(id=uid, title=uid, status='unavailable', selectable=False,
                       user_count=1, record_count=0, created_at=None,
                       warnings=['用研结果缺失或格式损坏，不能使用。'])


def _trend_metadata(root, identifier):
    """公开身份只接受固定历史登记及任务 UUID，绝不接受调用方目录。"""
    if identifier == 'history:' + HISTORY_ID:
        directory = root / HISTORY_PATH
        required = ('summary.json', 'execution.json', 'trend-clusters.json', 'trend-catalogue.json')
        for name in required:
            if not (directory / name).is_file():
                raise FileNotFoundError('历史趋势结果文件缺失')
        summary, execution = _read(directory / 'summary.json'), _read(directory / 'execution.json')
        clusters = _read(directory / 'trend-clusters.json')['clusters']
        catalogue = _read(directory / 'trend-catalogue.json')
        if not isinstance(clusters, list) or not isinstance(catalogue['articles'], list) or not isinstance(catalogue['evidence'], list):
            raise ValueError('历史趋势完整结果格式异常')
        return dict(id=identifier, title=f"历史趋势 · {len(clusters)} 个方向", status='completed',
                    selectable=bool(clusters), article_count=summary['articles'], trend_count=len(clusters),
                    created_at=execution.get('compiled_at'),
                    model_id=execution.get('selection_analysis', {}).get('model_id'), warnings=[LEGACY_NOTICE])
    if not identifier.startswith('task:') or not TASK_ID.fullmatch(identifier[5:]):
        raise ValueError('趋势输出标识无效')
    directory = root / 'data/result/article_trend_clustering' / identifier[5:]
    task = _read(directory / 'task.json')
    if task.get('id') != identifier[5:]:
        raise ValueError('趋势任务身份不一致')
    result = _read(directory / 'result.json') if task.get('status') == 'completed' else {}
    if task.get('status') == 'completed':
        records = _read(directory / 'records.json')
        if not isinstance(records, list) or not isinstance(result.get('trends'), list):
            raise ValueError('趋势结果格式异常')
        if result.get('records') != records:
            raise ValueError('趋势结果与冻结文章不一致')
    trends = result.get('trends', [])
    return dict(id=identifier, title=f"趋势洞察 · {len(trends)} 个方向 · {task.get('created_at', '')[:10]}",
                status=task['status'], selectable=task['status'] == 'completed' and bool(trends),
                article_count=task.get('article_count', 0), trend_count=len(trends),
                created_at=task.get('created_at'), model_id=task.get('model_id'),
                warnings=[] if trends else ['尚无已完成的正式趋势方向。'])


def list_inputs(root, *, research_store=None):
    """列出网页可选输出；未确认、未完成、损坏结果保留身份并明确禁用。"""
    root = Path(root).resolve()
    research = list(_registered_users(root, research_store or _store(root)))
    ids = []
    history = root / HISTORY_PATH
    if history.exists():
        ids.append('history:' + HISTORY_ID)
    directory = root / 'data/result/article_trend_clustering'
    if directory.exists():
        ids.extend('task:' + p.name for p in sorted(directory.iterdir()) if p.is_dir() and TASK_ID.fullmatch(p.name))
    trends = []
    for identifier in ids:
        try:
            trends.append(_trend_metadata(root, identifier))
        except (OSError, ValueError, KeyError, TypeError):
            trends.append(dict(id=identifier, title=identifier, status='unavailable', selectable=False,
                               article_count=0, trend_count=0, created_at=None, model_id=None,
                               warnings=['完整趋势结果缺失或损坏，不能使用；不会换用原始文章库。']))
    trends.sort(key=lambda row: row.get('created_at') or '', reverse=True)
    return dict(research_outputs=research, trend_outputs=trends)


class _Snapshots:
    def __init__(self, root):
        self.root, self.files = root, {}

    def read(self, key, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('上游文件超出工程目录')
        raw = path.read_bytes()
        text = raw.decode('utf-8')
        self.files[key] = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), content=text)
        return json.loads(text)

    def verify(self):
        # 构建期间发生人工确认或文件替换时明确拒绝，不能混合两个版本的证据。
        for item in self.files.values():
            if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('上游结果在读取期间发生变化，请重新预估')


def _safe_image(root, path):
    path = Path(path).resolve()
    boundaries = [root / 'data/trend_data', root / 'data/userreseach_data', root / 'data/result/user_research_intake']
    if not any(path.is_relative_to(p.resolve()) for p in boundaries) or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('关联图片超出允许的素材目录或文件类型不支持')
    return path


def _image_ref(path, rid, image_id, root, **metadata):
    path = _safe_image(root, path) if path else None
    return dict(image_id=image_id, source_record_id=rid, source_root=str(root),
                local_path=str(path.relative_to(root)) if path else None,
                status='available' if path and path.is_file() else 'missing', **metadata)


def _trend_images(root, snapshots, warnings):
    index = root / 'data/trend_data/trend_info_0930/trends.json'
    if not index.is_file():
        warnings.append('趋势图片索引缺失；原文仍可使用，关联图片无法提供。')
        return {}
    document = snapshots.read('trend_images', index)
    result = {}
    for row in document['trends']:
        aid = str(row['id'])
        refs = []
        for image in row.get('images', []):
            local = image.get('local_path')
            path = _safe_image(root, index.parent / local) if local else None
            ref = _image_ref(path, 'trend:' + aid, image.get('image_id'), root,
                             url=image.get('url'), sha256=image.get('sha256'),
                             association_level='article_attachment', visual_verified=False)
            refs.append(ref)
        result[aid] = refs
    return result


def _theme_context(theme):
    return {k: theme[k] for k in ('theme_id', 'cluster_id', 'title', 'definition', 'boundary',
                                  'boundaries', 'design_question', 'unknowns', 'priority_rank',
                                  'review_status') if k in theme}


def _summary_record(identifier, theme, key, pointer, anchors):
    """既有主题定义是上游分析结果；代表引文不能冒充全体成员全文已读。"""
    tid = theme.get('theme_id', theme.get('cluster_id'))
    if not tid or not theme.get('title') or not theme.get('definition'):
        raise ValueError('上游趋势缺少主题身份、标题或完整定义')
    return dict(id=f'trend_theme:{identifier}:{tid}', kind='trend',
        source_id='upstream_theme:' + tid,
        fields={'title_zh': theme['title'], 'summary_zh': theme['definition']},
        release_time=None, clustering_label=theme['title'], source_file=key, json_pointer=pointer,
        image_refs=[], semantic_context={
            'upstream_output_id': identifier, 'input_text_kind': 'upstream_summary',
            'source_role': 'analysis_note', 'memberships': [_theme_context(theme)],
            'representative_anchors': anchors,
            'reading_scope': '本轮阅读上游完整主题定义、边界和最多三段既有成员代表引文；完整成员原文已归档关联，未在本轮逐篇复读或复核。'})


def _load_trends(root, identifier, snapshots, images, warnings):
    """每篇文章只建一条来源，主次主题及逐点条件保留在语义上下文中。"""
    memberships = defaultdict(list)
    if identifier.startswith('task:'):
        directory = root / 'data/result/article_trend_clustering' / identifier[5:]
        task = snapshots.read('trend_task', directory / 'task.json')
        if task['status'] != 'completed':
            raise ValueError('只能使用已完成的趋势洞察结果')
        records = snapshots.read('trend_records', directory / 'records.json')
        result = snapshots.read('trend_result', directory / 'result.json')
        if result.get('records') != records:
            raise ValueError('趋势完整结果与冻结文章不一致')
        normalized = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if task.get('records_sha256') and hashlib.sha256(normalized.encode()).hexdigest() != task['records_sha256']:
            raise ValueError('趋势文章快照哈希不一致')
        themes = result['trends']
        for theme in themes:
            for relation in theme.get('reviews', []):
                memberships[str(relation['article_id'])].append({**_theme_context(theme),
                    'membership': relation, 'evidence_role': 'supported' if relation['status'] == 'supported' else 'boundary_only'})
        eligible = {str(m['article_id']) for theme in themes
                    for m in theme.get('members', []) + theme.get('secondary_members', [])}
        summaries = []
        for index, theme in enumerate(themes):
            anchors, seen = [], set()
            for position, relation in enumerate(theme.get('reviews', [])):
                aid = str(relation['article_id'])
                if relation.get('status') == 'supported' and aid not in seen and len(anchors) < 3:
                    seen.add(aid)
                    anchors.append(dict(text=relation['anchor'], source_record_id='trend:' + aid,
                        source_file='trend_result', json_pointer=f'/trends/{index}/reviews/{position}',
                        role=relation['role'], review_status=relation['status']))
            summaries.append(_summary_record(identifier, theme, 'trend_result', f'/trends/{index}', anchors))
        output = []
        for index, row in enumerate(records):
            aid = str(row['article_id'])
            if aid not in memberships:
                continue
            contexts = memberships[aid]
            # 未获支持但属于正式主题复核的文章保留为反证，不计为正向支持。
            output.append(dict(id='trend:' + aid, kind='trend', source_id=aid,
                fields={'title_zh': row['title'], 'summary_zh': row['summary']},
                release_time=row.get('published_at') or None,
                clustering_label=contexts[0]['title'], source_file='trend_records', json_pointer=f'/{index}',
                image_refs=images.get(aid, []), semantic_context={
                    'upstream_output_id': identifier, 'memberships': contexts,
                    'text_kind': row.get('text_kind'), 'source_group_id': row.get('source_group_id'),
                    'eligible_support': aid in eligible},
                source_lineage={'article_url': row.get('source_url')}))
        missing = set(memberships) - {str(r['article_id']) for r in records}
        if missing:
            raise ValueError('趋势主题引用了不存在的冻结文章')
        return output, len(records), len(themes), summaries

    directory = root / HISTORY_PATH
    catalogue = snapshots.read('trend_catalogue', directory / 'trend-catalogue.json')
    document = snapshots.read('trend_clusters', directory / 'trend-clusters.json')
    snapshots.read('trend_summary', directory / 'summary.json')
    snapshots.read('trend_execution', directory / 'execution.json')
    evidence = defaultdict(dict)
    for index, row in enumerate(catalogue['evidence']):
        evidence[row['source_id']][row['field']] = (row, index)
    summaries = []
    for theme_index, theme in enumerate(document['clusters']):
        selected, seen = set(theme['point_ids']), set()
        anchors, anchor_articles = [], set()
        per_article = defaultdict(list)
        for seed in theme.get('lineage', []):
            for point in seed.get('members', []):
                if point['point_id'] not in selected or point['point_id'] in seen:
                    continue
                seen.add(point['point_id'])
                sid = point['evidence_id'].rsplit(':', 1)[0]
                per_article[sid].append(point)
                if len(anchors) < 3 and sid not in anchor_articles:
                    anchor_articles.add(sid)
                    field = point['evidence_id'].rsplit(':', 1)[1]
                    source_evidence = evidence.get(sid, {}).get(field)
                    if source_evidence is None:
                        raise ValueError('历史主题代表引文对应原始证据缺失')
                    anchors.append(dict(text=point.get('quote', ''), source_record_id='trend:' + sid.removeprefix('T:'),
                        source_file='trend_catalogue', json_pointer=f'/evidence/{source_evidence[1]}',
                        point_id=point['point_id'], condition=point.get('condition'),
                        review_status=document.get('review_status', 'pending_human_review')))
        if selected != seen:
            raise ValueError('历史趋势有成员点缺失，不能截断使用')
        summary_theme = {**theme, 'review_status': document.get('review_status', 'pending_human_review')}
        summaries.append(_summary_record(identifier, summary_theme, 'trend_clusters', f'/clusters/{theme_index}', anchors))
        for sid, points in per_article.items():
            memberships[sid].append({**_theme_context(theme), 'role': 'legacy_member',
                'review_status': document.get('review_status', 'pending_human_review'),
                'points': points})
    output = []
    for index, article in enumerate(catalogue['articles']):
        sid = article['source_id']
        if sid not in memberships:
            continue
        aid = str(article['original_id'])
        fields = evidence[sid]
        if 'summary_zh' not in fields or not ('title_zh' in fields or 'title' in fields):
            raise ValueError('历史趋势缺少完整标题或摘要证据')
        title_row = fields.get('title_zh', fields.get('title'))[0]
        output.append(dict(id='trend:' + aid, kind='trend', source_id=aid,
            fields={'title_zh': title_row['text'], 'summary_zh': fields['summary_zh'][0]['text']},
            release_time=article.get('metadata', {}).get('release_time'),
            clustering_label=memberships[sid][0]['title'], source_file='trend_catalogue', json_pointer=f'/articles/{index}',
            image_refs=images.get(aid, []), semantic_context={
                'upstream_output_id': identifier, 'memberships': memberships[sid],
                'review_status': document.get('review_status', 'pending_human_review'),
                'text_kind': title_row.get('text_kind'), 'source_group_id': article.get('source_group_id')},
            source_lineage={'article_url': article.get('metadata', {}).get('detail_url'),
                'evidence_locations': [{'source_file': 'trend_catalogue', 'json_pointer': f'/evidence/{i}'}
                                       for _, i in fields.values()]}))
    if set(memberships) - {a['source_id'] for a in catalogue['articles']}:
        raise ValueError('历史趋势成员文章缺失')
    warnings.append(LEGACY_NOTICE)
    return output, len(catalogue['articles']), len(document['clusters']), summaries


def build_source_data(root, research_ids: list[str], trend_result_id: str, *, research_store=None):
    """使用明确选择的完整模块输出，返回可由 lean.prepare 落盘的原始字节快照。"""
    root = Path(root).resolve()
    if not research_ids or len(set(research_ids)) != len(research_ids):
        raise ValueError('请选择至少一份用研输出，且不能重复')
    store = research_store or _store(root)
    registered = {r['id']: r for r in _registered_users(root, store)}
    chosen = []
    for uid in research_ids:
        if uid not in registered or not registered[uid]['selectable']:
            raise ValueError('所选用研不存在、未确认或不可用：' + str(uid))
        chosen.append(registered[uid])
    trend = _trend_metadata(root, trend_result_id)
    if not trend['selectable']:
        raise ValueError('所选趋势输出尚未完成或没有正式方向')
    snapshots, warnings = _Snapshots(root), []
    images = _trend_images(root, snapshots, warnings)
    trends, article_count, trend_count, summaries = _load_trends(root, trend_result_id, snapshots, images, warnings)
    sources = {f'T{i:05}': row for i, row in enumerate(trends + summaries, 1)}
    model_trend_ids = [f'T{i:05}' for i in range(len(trends) + 1, len(trends) + len(summaries) + 1)]
    inventory, user_rows, text_users = {}, [], set()
    seed = None
    for uid in research_ids:
        detail = store.get_user(uid)
        if detail['status'] != 'ready':
            raise ValueError('用研状态已变化，请重新预估')
        warnings.extend(detail.get('warnings', []))
        raw_by_id = {}
        if uid.startswith('import_'):
            key = 'research_' + uid
            document = snapshots.read(key, store.root / uid[7:] / 'user.json')
            if document.get('id') != uid or document.get('status') != 'ready':
                raise ValueError('用研登记身份或确认状态不一致')
            for index, row in enumerate(document['records']):
                raw_by_id[str(row['id'])] = (row, key, f'/records/{index}', 'user_qa')
            asset_path = store.root / uid[7:] / 'assets.json'
            if asset_path.is_file():
                snapshots.read(key + '_assets', asset_path)
        else:
            if seed is None:
                seed = snapshots.read('research_seed', store.seed_file)
                recovery_index = store.image_root / 'images.json'
                if recovery_index.is_file():
                    snapshots.read('research_image_index', recovery_index)
            user_index, user = next(((i, u) for i, u in enumerate(seed['users']) if str(u['id']) == uid), (None, None))
            if user is None:
                raise ValueError('用研来源用户已移除')
            for section, kind in (('aesthetic_research', 'user_qa'), ('demand_research', 'user_demand')):
                for index, row in enumerate(user.get(section, [])):
                    if row.get('source_type') == 'ppt_supplement':
                        raw_by_id[str(row['id'])] = (row, 'research_seed', f'/users/{user_index}/{section}/{index}', kind)
        # 原始字节先冻结，再取当前 DTO；末尾校验快照可发现读取期间的确认/编辑。
        detail = store.get_user(uid)
        if detail.get('status') != 'ready':
            raise ValueError('用研状态已变化，请重新预估')
        detail_images = {x['id']: x for x in detail['images']}
        for record in detail['records']:
            if str(record['id']) not in raw_by_id:
                raise ValueError('用研展示记录与完整来源不一致')
            original, key, pointer, kind = raw_by_id[str(record['id'])]
            answer = original.get('answer', original.get('ai_analysis', original.get('ai_index')))
            if answer is None or not str(answer).strip():
                continue
            rid = f'user:{uid}:{kind}:{record["id"]}'
            associations, refs = [], []
            for iid in record.get('imageIds', []):
                if iid not in detail_images:
                    raise ValueError('用研回答引用了未知图片关系')
                image = detail_images[iid]
                associations.append({k: image[k] for k in ('id', 'code', 'emotion', 'sourceSlide', 'questionId', 'evidenceScope', 'status') if k in image})
                if image.get('emotion') not in ('ENJOY', 'LIKE'):
                    continue
                try:
                    path = _safe_image(root, store.asset_path(uid, iid))
                except FileNotFoundError:
                    path = None
                ref = _image_ref(path, rid, iid, root, code=image.get('code'), emotion_tag=image['emotion'],
                                 association_level='explicit_record_link', visual_verified=False)
                refs.append(ref)
                if path:
                    entry = inventory.setdefault(str(path), dict(path=str(path), file_exists=path.is_file(),
                        user_ids=[], image_ids=[], codes=[], source_locations=[], emotion_tags=[],
                        association_level='selected_user_attachment', visual_verified=False))
                    for name, value in (('user_ids', uid), ('image_ids', iid), ('codes', image.get('code')), ('emotion_tags', image['emotion'])):
                        if value is not None and value not in entry[name]:
                            entry[name].append(value)
                    entry['source_locations'].append(dict(user_id=uid, source_file=key, json_pointer=pointer))
            fields = {'question': original.get('question', record.get('question', '')), 'ai_analysis': answer} if kind == 'user_qa' else {'scenario': original.get('scenario', record.get('section', '')), 'ai_index': answer}
            user_rows.append(dict(id=rid, kind=kind, source_id=str(record['id']), user_id=uid,
                profile=detail.get('profile', {}), fields=fields, source_file=key, json_pointer=pointer,
                image_refs=refs,
                source_lineage={'image_associations': [detail_images[iid] for iid in record.get('imageIds', [])]},
                semantic_context={
                    'upstream_output_id': uid, 'sourceRole': original.get('sourceRole', original.get('source_role', 'user_response')),
                    'originalAnswer': original.get('originalAnswer', original.get('original_answer')),
                    'source_language': original.get('source_language', detail.get('provenance', {}).get('sourceLanguage')),
                    'answer_type': original.get('answer_type', detail.get('provenance', {}).get('textKind')),
                    'source_slide': original.get('sourceSlide', original.get('source_slide', record.get('sourceSlide'))),
                    'source_file': original.get('sourceFile', original.get('source_file', record.get('sourceFile'))),
                    'attitudes': associations, 'confirmation_status': detail['status']}))
            text_users.add(uid)
    if not user_rows or not trends:
        raise ValueError('所选模块输出没有足够的完整文字资料')
    sources.update({f'U{i:06}': row for i, row in enumerate(user_rows, 1)})
    model_source_ids = model_trend_ids + [f'U{i:06}' for i in range(1, len(user_rows) + 1)]
    categories, category_articles = defaultdict(list), defaultdict(set)
    articles_by_theme = defaultdict(set)
    for row in trends:
        for membership in row['semantic_context']['memberships']:
            tid = membership.get('theme_id', membership.get('cluster_id'))
            articles_by_theme[tid].add(row['source_id'])
    for alias in model_trend_ids:
        row = sources[alias]
        label = row['clustering_label']
        categories[label].append(alias)
        # source_ids 供模型选取摘要；文章数单独按父主题的原始文章身份去重。
        for membership in row['semantic_context']['memberships']:
            tid = membership.get('theme_id', membership.get('cluster_id'))
            category_articles[label].update(articles_by_theme[tid])
    snapshots.verify()
    return dict(project_root=str(root), sources=sources, user_image_inventory=list(inventory.values()),
        trend_categories=[dict(label=label, source_ids=ids, article_count=len(category_articles[label])) for label, ids in categories.items()],
        inputs={key: {k: v for k, v in item.items() if k != 'content'} for key, item in snapshots.files.items()},
        input_snapshots=snapshots.files, model_source_ids=model_source_ids,
        model_input_scope=dict(mode='existing_theme_handshake',
            trend_theme_count=len(summaries), representative_anchor_limit_per_theme=3,
            full_member_articles_archived=len(trends), full_member_articles_reread=False,
            research_records_read=len(user_rows),
            description='用研完整回答与既有趋势主题完整定义、边界及最多三段代表引文握手；全部成员文章与图片保留关联，但本轮不声称逐篇重新复核。'),
        upstream_selection={'research_outputs': chosen, 'trend_output': trend},
        warnings=list(dict.fromkeys(warnings)),
        selection=dict(mode='module_outputs', research_ids=research_ids, trend_result_id=trend_result_id,
                       selected_user_ids=research_ids, user_limit=None, start_date=None, end_date=None,
                       inclusive=True, undated_policy='include', undated_in_source=0, excluded={}),
        counts=dict(source_trends=article_count, selected_trends=len(trends), trend_records=len(trends),
                    trend_cluster_count=len(summaries), model_trend_records=len(summaries), model_user_records=len(user_rows),
                    upstream_trend_count=trend_count, source_users=len(research_ids), selected_users=len(research_ids),
                    users=len(research_ids), users_with_text=len(text_users), user_records=len(user_rows),
                    source_records=len(sources), excluded_unmentioned_qa=0, excluded_empty_qa=0,
                    excluded_empty_demand=0, excluded_unlinked_demands=0, excluded_users_by_limit=0))

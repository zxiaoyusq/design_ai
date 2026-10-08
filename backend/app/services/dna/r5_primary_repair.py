"""R5原回复的离线保守投影：保留合法字段，隔离未知值，不推断视觉事实。"""

from copy import deepcopy
import json
import math

VERSION = 'r5-conservative-local-repair-v1'


class _ObjectPairs(list):
    """区别JSON对象与数组，使重复键能够逐路径留痕而不后值覆盖。"""


def parse_primary(raw):
    text = raw.strip()
    audit = []
    if text.startswith('```') and text.endswith('```'):
        text = '\n'.join(text.splitlines()[1:-1]).strip()
        audit.append({'kind': 'remove_markdown_fence', 'path': ''})
    def reject_constant(value):
        raise ValueError('非有限JSON数值：' + value)
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            reject_constant(value)
        return result
    parsed = json.loads(text, object_pairs_hook=_ObjectPairs, parse_constant=reject_constant, parse_float=finite_float)
    def convert(value, path):
        if isinstance(value, _ObjectPairs):
            groups = {}
            for key, child in value:
                groups.setdefault(key, []).append(convert(child, path + '/' + escape(key)))
            result = {}
            for key, variants in groups.items():
                if len(variants) > 1:
                    identical = len({json.dumps(v, ensure_ascii=False, sort_keys=True, allow_nan=False) for v in variants}) == 1
                    audit.append({'kind': 'deduplicate_identical_key' if identical else 'duplicate_key_conflict',
                                  'path': path + '/' + escape(key), 'original_values': variants})
                    if not identical:
                        continue  # 冲突字段缺失后由领域校验补unknown或隔离所属记录。
                result[key] = variants[0]
            return result
        if isinstance(value, list):
            return [convert(v, path + '/' + str(i)) for i, v in enumerate(value)]
        return value
    answer = convert(parsed, '')
    if not isinstance(answer, dict):
        raise ValueError('初提回复必须是单个JSON对象')
    return answer, audit


def escape(key):
    return str(key).replace('~', '~0').replace('/', '~1')


def recover_primary(raw, portable, engine):
    """生成严格合规的候选投影；非法取值只隔离，绝不猜近义词或补custom。"""
    answer, audit = parse_primary(raw)
    schema = engine.schema()
    validator_type = engine.c.jsonschema.Draft202012Validator
    validators = {}
    quarantined = [dict(row, reason='重复JSON键值冲突，未自动择值')
                   for row in audit if row['kind'] == 'duplicate_key_conflict']
    source_paths = {}

    def valid(value, spec):
        key = json.dumps(spec, sort_keys=True)
        if key not in validators:
            validators[key] = validator_type({'$defs': schema['$defs'], **spec})
        return validators[key].is_valid(value)

    def isolate(path, value, reason):
        row = {'kind': 'quarantine', 'path': path, 'original': deepcopy(value), 'reason': reason}
        audit.append(row)
        quarantined.append(row)

    def extras(value, allowed, path):
        for key in value.keys() - set(allowed):
            isolate(path + '/' + escape(key), value[key], '不属于此结构的字段，保留原值供人工复核')

    def nullable(value, pid, path, missing=False):
        if missing:
            audit.append({'kind': 'fill_unknown', 'path': path, 'reason': '遗漏的可空字段补null，不推断取值'})
            return None
        if value is None:
            return None
        spec = schema['$defs']['v_' + pid]
        if valid(value, spec):
            return deepcopy(value)
        if isinstance(value, str) and valid(value.strip(), spec):
            audit.append({'kind': 'trim_exact', 'path': path, 'original': value, 'normalized': value.strip()})
            return value.strip()
        isolate(path, value, '不符合该字段冻结类型或候选值；保留未知，不猜测替换')
        return None

    def field(row, allowed, path):
        if not isinstance(row, dict) or row.get('p') not in allowed or 'v' not in row:
            isolate(path, row, '字段编号缺失、未知或不允许出现在此位置')
            return None
        pid = row['p']
        extras(row, ['p', 'v'], path)
        value = nullable(row['v'], pid, path + '/v')
        if value is None:
            if row['v'] is None:
                isolate(path, row, '此字段条目不接受null；未知值不进入已知特征')
            return None
        return {'p': pid, 'v': value}

    def location(value, spec, path):
        if valid(value, spec):
            return value
        if isinstance(value, str) and valid(value.strip(), spec):
            audit.append({'kind': 'trim_exact', 'path': path, 'original': value, 'normalized': value.strip()})
            return value.strip()
        return None

    if not isinstance(answer.get('areas'), list):
        raise ValueError('缺少可识别的区域清单，不能补造区域')
    projected = {'areas': [], 'overall': [], 'uncertain': []}
    extras(answer, projected, '')
    area_spec = schema['properties']['areas']['items']['properties']
    for i, area in enumerate(answer['areas']):
        original = f'/areas/{i}'
        if not isinstance(area, dict):
            isolate(original, area, '区域不是对象')
            continue
        name = location(area.get('name'), area_spec['name'], original + '/name')
        if name is None:
            isolate(original, area, '位置名称缺失或不合规，不能补造或截断位置')
            continue
        target = f'/areas/{len(projected["areas"])}'
        source_paths[target] = original
        extras(area, ['name', 'base', 'texture', 'more'], original)
        base = area.get('base')
        if not isinstance(base, dict):
            isolate(original + '/base', base, 'base缺失或结构错误，四项全部保持未知')
            base = {}
        extras(base, engine.CORE, original + '/base')
        normalized_base = {pid: nullable(base.get(pid), pid, original + '/base/' + pid, pid not in base)
                           for pid in engine.CORE}
        texture = area.get('texture')
        if not isinstance(texture, dict) or texture.get('state') not in ('none', 'uncertain', 'visible'):
            isolate(original + '/texture', texture, '纹理状态不合规，不能自动断言有无纹理')
            normalized_texture = {'state': 'uncertain'}
        elif texture['state'] != 'visible':
            extras(texture, ['state'], original + '/texture')
            normalized_texture = {'state': texture['state']}
        else:
            dna = deepcopy(texture.get('dna'))
            if not isinstance(dna, dict):
                isolate(original + '/texture/dna', dna, '可见纹理字段对象缺失，具体特征保持未知')
                dna = {}
            for pid in engine.TEX:
                if pid in texture:
                    value = texture[pid]
                    if pid not in dna and valid(value, {'anyOf': [schema['$defs']['v_' + pid], {'type': 'null'}]}):
                        dna[pid] = deepcopy(value)
                        source_paths[target + '/texture/dna/' + pid] = original + '/texture/' + pid
                        audit.append({'kind': 'move_field', 'path': original + '/texture/' + pid,
                                      'projected_path': target + '/texture/dna/' + pid, 'original': value})
                    else:
                        isolate(original + '/texture/' + pid, value, '错层字段目标已有值或自身不合规，不能覆盖')
                        if pid in dna and dna[pid] != value:
                            isolate(original + '/texture/dna/' + pid, dna[pid], '同位置同字段出现冲突，双方均暂缓')
                            dna[pid] = None
            extras(texture, ['state', 'dna', *engine.TEX], original + '/texture')
            extras(dna, engine.TEX, original + '/texture/dna')
            normalized_texture = {'state': 'visible', 'dna': {
                pid: nullable(dna.get(pid), pid, original + '/texture/dna/' + pid, pid not in dna)
                for pid in engine.TEX}}
        more = area.get('more', [])
        if not isinstance(more, list):
            isolate(original + '/more', more, '额外字段不是数组，不能猜测展开')
            more = []
        normalized_more = []
        for j, row in enumerate(more):
            path = original + f'/more/{j}'
            result = field(row, [pid for pid in engine.CMF if pid not in engine.CORE + engine.TEX], path)
            if result is not None:
                source_paths[target + f'/more/{len(normalized_more)}'] = path
                normalized_more.append(result)
        projected['areas'].append({'name': name, 'base': normalized_base,
                                   'texture': normalized_texture, 'more': normalized_more})
    if not projected['areas']:
        raise ValueError('没有可保留的合法位置；不能生成伪区域')
    for group in ('overall', 'uncertain'):
        rows = answer.get(group, [])
        if not isinstance(rows, list):
            isolate('/' + group, rows, '条目清单不是数组')
            continue
        spec = schema['properties'][group]['items']['properties']
        for i, original_row in enumerate(rows):
            path = f'/{group}/{i}'
            if not isinstance(original_row, dict):
                isolate(path, original_row, '条目不是对象')
                continue
            row = deepcopy(original_row)
            # reason误放dna内部且外部缺失时只调整层级，保留原文。
            if group == 'uncertain' and 'reason' not in row and isinstance(row.get('dna'), dict) and 'reason' in row['dna']:
                row['reason'] = row['dna'].pop('reason')
                audit.append({'kind': 'move_field', 'path': path + '/dna/reason', 'projected_path': path + '/reason'})
            at = location(row.get('at'), spec['at'], path + '/at')
            if at is None or (group == 'uncertain' and not valid(row.get('reason'), spec['reason'])):
                isolate(path, original_row, '位置或未决原因不合规，不能补造')
                continue
            dna = field(row.get('dna'), [pid for pid in engine.ACTIVE if group == 'uncertain' or pid not in engine.CORE], path + '/dna')
            if dna is None:
                continue
            if group == 'uncertain' and len(projected[group]) >= 6:
                isolate(path, original_row, '超过冻结协议6项未决上限，保留原项供人工复核')
                continue
            extras(row, spec, path)
            source_paths[f'/{group}/{len(projected[group])}'] = path
            projected[group].append({'at': at, 'dna': dna, **({'reason': row['reason']} if group == 'uncertain' else {})})
    portable.validate(engine, schema, projected)
    blocked = set()
    # 隔离错放/非法的一条候选后，同位置同字段的另一条候选也不能自动胜出。
    for row in quarantined:
        parts = row['path'].strip('/').split('/')
        try:
            if parts[0] == 'areas' and len(parts) >= 3:
                area = answer['areas'][int(parts[1])]
                at = area['name']
                if parts[2] == 'base' and len(parts) >= 4:
                    blocked.add((at, parts[3]))
                elif parts[2] == 'more' and len(parts) >= 4:
                    blocked.add((at, area['more'][int(parts[3])]['p']))
                elif parts[2] == 'texture':
                    pid = parts[-1]
                    blocked.update((at, p) for p in ([pid] if pid in engine.TEX else engine.TEX))
            elif parts[0] in ('overall', 'uncertain') and len(parts) >= 2:
                item = answer[parts[0]][int(parts[1])]
                blocked.add((item['at'], item['dna']['p']))
        except (IndexError, KeyError, TypeError, ValueError):
            continue
    return {'answer': projected, 'audit': audit, 'quarantined': quarantined,
            'blocked_fields': [{'at': at, 'p': pid} for at, pid in sorted(blocked)],
            'source_paths': source_paths, 'version': VERSION}


def original_paths(value, source_paths):
    """数组隔离会改变下标：输出证据指回原回复，同时保留投影路径。"""
    if isinstance(value, list):
        return [original_paths(item, source_paths) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: original_paths(item, source_paths) for key, item in value.items()}
    path = result.get('path')
    if isinstance(path, str):
        for projected, original in sorted(source_paths.items(), key=lambda pair: -len(pair[0])):
            if path == projected or path.startswith(projected + '/'):
                result['projection_path'] = path
                result['path'] = original + path[len(projected):]
                break
    return result

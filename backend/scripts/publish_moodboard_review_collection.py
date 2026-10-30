"""发布指定PPT与网页图板的逐图标注集合，保留原图字节、顺序及显示取景。"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
import shutil
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PIL import Image


PROJECT = Path(__file__).resolve().parents[2]
DOMAIN = 'https://gamedevcenter.ahagamecenter.com'
REFERENCE = 'dna-cluster-sample1600-reference-20261010'
BOUNDED = 'dna-cluster-sample1600-bounded-three-20261012'
NS = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list[Node] = field(default_factory=list)
    text: list[str] = field(default_factory=list)

    def find(self, tag: str, cls: str | None = None) -> list[Node]:
        result = []
        for child in self.children:
            if child.tag == tag and (cls is None or cls in child.attrs.get('class', '').split()):
                result.append(child)
            result.extend(child.find(tag, cls))
        return result

    def content(self) -> str:
        return ''.join(self.text).strip()


class PageParser(HTMLParser):
    """只读取页面结构和原文；JSON脚本由独立入口解析，不执行任何源页面脚本。"""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.root = Node('root', {})
        self.stack = [self.root]
        self.feed(re.sub(r'<(?:script|style)\b[^>]*>[\s\S]*?</(?:script|style)>', '', html))

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {'meta', 'link', 'br', 'hr', 'img', 'input', 'source', 'wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        for node in self.stack:
            node.text.append(data)


def page_data(html: str, script_id: str) -> dict:
    match = re.search(r'<script\b[^>]*\bid=["\']' + re.escape(script_id) + r'["\'][^>]*>([\s\S]*?)</script>', html)
    if match is None:
        raise ValueError(f'页面缺少图片数据：{script_id}')
    return json.loads(match[1])


class Assets:
    def __init__(self, output: Path):
        self.output = output
        self.records = {}
        (output / 'assets').mkdir()

    def add(self, content: bytes, expected: str | None = None) -> dict:
        digest = sha(content)
        if expected and digest != expected:
            raise ValueError(f'原图SHA不一致：{expected}')
        if digest in self.records:
            return self.records[digest]
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif', 'AVIF': 'avif'}.get(image.format)
            if not extension:
                raise ValueError(f'不支持的图片格式：{image.format}')
        relative = f'assets/{digest}.{extension}'
        (self.output / relative).write_bytes(content)
        record = {'path': relative, 'sha256': digest, 'width': width, 'height': height, 'bytes': len(content)}
        self.records[digest] = record
        return record

    def from_page(self, root: Path, url: str, expected: str | None = None) -> dict:
        if url.startswith('data:'):
            prefix, encoded = url.split(',', 1)
            if ';base64' not in prefix:
                raise ValueError('图片数据并非base64')
            return self.add(base64.b64decode(encoded, validate=True), expected)
        file = (root / url).resolve()
        if not file.is_relative_to(root.resolve()) or not file.is_file():
            raise ValueError(f'图片路径超出指定来源或不存在：{url}')
        return self.add(file.read_bytes(), expected)


def ppt_box(shape: ET.Element, width: int, height: int) -> list[float]:
    transform = shape.find('p:spPr/a:xfrm', NS)
    if transform is None:
        raise ValueError('PPT形状缺少绝对位置')
    if any(transform.get(key) not in (None, '0') for key in ('rot', 'flipH', 'flipV')):
        raise ValueError('PPT存在未支持的旋转或翻转，不能静默改变版式')
    offset, extent = transform.find('a:off', NS), transform.find('a:ext', NS)
    return [int(offset.get('x')) / width, int(offset.get('y')) / height,
            int(extent.get('cx')) / width, int(extent.get('cy')) / height]


def ppt_boards(file: Path, assets: Assets) -> tuple[list[dict], dict]:
    result = []
    with ZipFile(file) as archive:
        presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
        size = presentation.find('p:sldSz', NS)
        width, height = int(size.get('cx')), int(size.get('cy'))
        relationships = ET.fromstring(archive.read('ppt/_rels/presentation.xml.rels'))
        # OOXML关系既可相对定位，也可从包根以/ppt/...定位；ZIP条目不带开头斜线。
        slide_files = {item.get('Id'): posixpath.normpath(posixpath.join('ppt', item.get('Target'))).lstrip('/') for item in relationships}
        # 按presentation声明顺序读取，不能用主题编号或媒体文件名重排幻灯片。
        for ordinal, slide_id in enumerate(presentation.findall('p:sldIdLst/p:sldId', NS), 1):
            part = slide_files[slide_id.get(f'{{{NS["r"]}}}id')]
            slide = ET.fromstring(archive.read(part))
            rel_part = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
            rels = {item.get('Id'): item for item in ET.fromstring(archive.read(rel_part))}
            tree = slide.find('p:cSld/p:spTree', NS)
            if tree.findall('p:grpSp', NS):
                raise ValueError('当前PPT存在组合坐标，需要单独适配')
            texts = [''.join(node.itertext()).strip() for node in slide.findall('.//a:t', NS)]
            board_id = f'ppt-slide-{ordinal}'
            board = {'id': board_id, 'source': 'ppt', 'source_label': '老师 PPT', 'source_index': ordinal,
                     'title': texts[2] if len(texts) > 2 else f'第{ordinal}页', 'subtitle': texts[1] if len(texts) > 1 else '',
                     'source_state': 'PPT 原版', 'notes': f'源文件第 {ordinal} 页，点击板中图片可标注。',
                     'layout': 'ppt', 'aspect': width / height, 'layers': [], 'images': []}
            for shape in tree:
                kind = shape.tag.rsplit('}', 1)[-1]
                if kind == 'pic':
                    info = shape.find('p:nvPicPr/p:cNvPr', NS)
                    blip = shape.find('p:blipFill/a:blip', NS)
                    relation = rels[blip.get(f'{{{NS["r"]}}}embed')]
                    if relation.get('TargetMode') == 'External':
                        raise ValueError('PPT图片依赖外部文件')
                    media = posixpath.normpath(posixpath.join(posixpath.dirname(part), relation.get('Target'))).lstrip('/')
                    original = assets.add(archive.read(media))
                    rect = shape.find('p:blipFill/a:srcRect', NS)
                    left, top, right, bottom = [int(rect.get(key, '0')) / 100000 if rect is not None else 0 for key in ('l', 't', 'r', 'b')]
                    roi = [left, top, 1 - left - right, 1 - top - bottom]
                    if roi[2] <= 0 or roi[3] <= 0:
                        raise ValueError('PPT裁切范围无效')
                    tile = {'id': f'{board_id}:shape-{info.get("id")}', 'image_id': f'PPT{ordinal}-{len(board["images"]) + 1}',
                            'label': f'第 {ordinal} 页 · 图片 {len(board["images"]) + 1}', 'sha256': original['sha256'],
                            'original': original['path'], 'preview': original['path'], 'dimensions': [original['width'], original['height']],
                            'roi': roi, 'preview_roi': roi, 'ppt_shape_id': info.get('id'), 'ppt_media_part': media,
                            'box': ppt_box(shape, width, height), 'sources': [], 'scope': '沿用 PPT 的原始裁切位置。'}
                    board['images'].append(tile)
                    board['layers'].append({'type': 'image', 'image_id': tile['id']})
                elif kind == 'sp':
                    body = shape.find('p:txBody', NS)
                    if body is None:
                        continue
                    paragraphs = [''.join(p.itertext()).strip() for p in body.findall('a:p', NS)]
                    text = '\n'.join(paragraphs).strip()
                    if not text:
                        continue
                    properties = body.find('.//a:rPr', NS)
                    if properties is None:
                        properties = body.find('.//a:defRPr', NS)
                    color = properties.find('a:solidFill/a:srgbClr', NS) if properties is not None else None
                    align = body.find('a:p/a:pPr', NS)
                    board['layers'].append({'type': 'text', 'text': text, 'box': ppt_box(shape, width, height),
                                            'font_ratio': int(properties.get('sz', '1200')) / 100 * 12700 / width if properties is not None else 0.012,
                                            'bold': properties is not None and properties.get('b') == '1',
                                            'color': '#' + color.get('val') if color is not None else '#332f29',
                                            'align': {'ctr': 'center', 'r': 'right'}.get(align.get('algn') if align is not None else None, 'left')})
            result.append(board)
    if len(result) != 5 or any(len(board['images']) != 8 for board in result):
        raise ValueError('PPT的页数或逐页图片数与当前5页×8图输入不一致')
    return result, {'kind': 'ppt', 'source_name': file.name, 'sha256': sha(file.read_bytes()), 'board_count': 5}


def web_tile(member: dict, asset: dict, node: Node, root: Path, board_id: str, assets: Assets) -> dict:
    original = assets.from_page(root, asset['path'], member['sha256'])
    image = node.find('img')[0]
    # 已渲染的真实裁片与完整原图分别保留；不能把裁片再次当作原图裁切。
    cropped = bool(image.attrs.get('data-crop-sha'))
    preview_path = image.attrs['src'] if cropped else asset.get('preview_path', asset['path'])
    preview = assets.from_page(root, preview_path, image.attrs.get('data-crop-sha') if cropped else None)
    roi = member.get('roi', [0, 0, 1, 1])
    source_links = [{'title': source.get('title', '来源文章'), 'url': source['article_url']}
                    for source in asset.get('sources', []) if source.get('article_url', '').startswith(('http://', 'https://'))]
    return {'id': f'{board_id}:{member.get("unit_id", member["image_id"])}', 'image_id': member['image_id'],
            'unit_id': member.get('unit_id'), 'label': member['image_id'], 'sha256': member['sha256'],
            'original': original['path'], 'preview': preview['path'], 'dimensions': [original['width'], original['height']],
            'preview_dimensions': [preview['width'], preview['height']],
            'roi': roi, 'preview_roi': [0, 0, 1, 1] if cropped else roi, 'sources': source_links,
            'scope': member.get('crop_reason') or member.get('reason') or member.get('scope', ''),
            'preview_frame_index': asset.get('preview_frame_index')}


def reference_boards(root: Path, assets: Assets) -> tuple[list[dict], dict]:
    content = (root / 'index.html').read_text(encoding='utf-8')
    data = page_data(content, 'preview-data')
    binding = page_data(content, 'renderer-binding')
    overrides = binding.get('layout', {}).get('config', {})
    sections = PageParser(content).root.find('section', 'group')[:4]
    groups = {group['group_id']: group for group in data['groups']}
    result = []
    for ordinal, section in enumerate(sections, 1):
        group = groups[section.attrs['data-group']]
        board_id = f'reference-{group["group_id"]}'
        board = {'id': board_id, 'source': 'reference', 'source_label': '参考网页 · 前 4 板', 'source_index': ordinal,
                 'title': group['title'], 'source_state': group['label'], 'notes': section.find('p', 'group-meta')[0].content(),
                 'source_url': f'{DOMAIN}/visual-workflow/{REFERENCE}/index.html', 'layout': 'grid', 'images': []}
        for figure in section.find('figure', 'tile'):
            member = data['views'][int(figure.attrs['data-view'])]
            tile = web_tile(member, data['assets'][member['sha256']], figure, root, board_id, assets)
            if group['kind'] == 'candidate' and member['unit_id'] in overrides:
                tile['layout_override'] = overrides[member['unit_id']]
            board['images'].append(tile)
        special_layout = any(tile.get('layout_override') for tile in board['images'])
        board.update(columns=3 if special_layout else 4, tile_height=300 if special_layout else 245,
                     mobile_tile_height=190 if special_layout else 140)
        if [tile['unit_id'] for tile in board['images']] != [member['unit_id'] for member in group['members']]:
            raise ValueError('参考页实际DOM顺序与成员声明不一致')
        result.append(board)
    if len(result) != 4:
        raise ValueError('参考页面不足4板')
    return result, {'kind': 'reference', 'url': f'{DOMAIN}/visual-workflow/{REFERENCE}/index.html',
                    'sha256': sha(content.encode('utf-8')), 'selected_board_ids': [b['id'] for b in result]}


def bounded_boards(root: Path, assets: Assets) -> tuple[list[dict], dict]:
    content = (root / 'index.html').read_text(encoding='utf-8')
    data = page_data(content, 'page-data')
    sections = PageParser(content).root.find('section', 'bounded-board')
    result = []
    for ordinal, section in enumerate(sections, 1):
        board_id = f'bounded-{ordinal}'
        status = section.find('p', 'bounded-status')
        notes = section.find('p', 'bounded-note')
        board = {'id': board_id, 'source': 'bounded', 'source_label': '本轮网页 · 3 板', 'source_index': ordinal,
                 'title': section.find('h2')[0].content(), 'source_state': status[0].content() if status else '候选板',
                 'notes': notes[0].content() if notes else '',
                 'source_url': f'{DOMAIN}/visual-workflow/{BOUNDED}/index.html', 'layout': 'grid', 'images': []}
        board.update(columns=3, tile_height=228, mobile_tile_height=165)
        for figure in section.find('figure', 'tile'):
            index = int(figure.find('button', 'tile-open')[0].attrs['data-member-index'])
            member = data['board']['members'][index]
            asset = {'path': member['asset_url'], 'sources': member.get('sources', [])}
            board['images'].append(web_tile(member, asset, figure, root, board_id, assets))
        result.append(board)
    if len(result) != 3 or any(len(b['images']) != 5 for b in result):
        raise ValueError('本轮实际板数或图片数与3板×5图不一致')
    return result, {'kind': 'bounded', 'url': f'{DOMAIN}/visual-workflow/{BOUNDED}/index.html',
                    'sha256': sha(content.encode('utf-8')), 'selected_board_ids': [b['id'] for b in result]}


def validate_ranking(ranking: dict, identity: str, boards: list[dict]) -> dict:
    """排名必须完整绑定当前集合；不能因缺板、重号或身份变动迁移用户标注。"""
    if not isinstance(ranking, dict) or ranking.get('collection_identity') != identity:
        raise ValueError('排名集合身份与当前图片集合不一致')
    entries = ranking.get('entries')
    if not isinstance(entries, list) or len(entries) != len(boards):
        raise ValueError('排名必须覆盖当前集合的全部图板')
    board_ids = {board['id'] for board in boards}
    seen_ids, seen_ranks = set(), set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('每个排名条目必须是对象')
        board_id, rank, reason = entry.get('board_id'), entry.get('rank'), entry.get('reason')
        if not isinstance(board_id, str) or board_id not in board_ids or board_id in seen_ids:
            raise ValueError('排名存在未知图板或重复图板')
        if type(rank) is not int or not 1 <= rank <= len(boards) or rank in seen_ranks:
            raise ValueError('排名必须是从1到图板总数的不重复整数')
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('每个图板的排名必须附有简短判断理由')
        seen_ids.add(board_id)
        seen_ranks.add(rank)
    return ranking


def publish(ppt: Path, output: Path, ranking_file: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    assets = Assets(output)
    ppt_result, ppt_source = ppt_boards(ppt, assets)
    reference, reference_source = reference_boards(PROJECT / 'frontend/public/visual-workflow' / REFERENCE, assets)
    bounded, bounded_source = bounded_boards(PROJECT / 'frontend/public/visual-workflow' / BOUNDED, assets)
    boards = ppt_result + reference + bounded
    sources = [ppt_source, reference_source, bounded_source]
    identity = sha(json.dumps(sources, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    data = {'schema_version': 'prism.image_rejection_collection.v1', 'identity': identity,
            'title': '情绪板对照与逐图标注', 'boards': boards, 'sources': sources,
            'board_count': len(boards), 'image_count': sum(len(b['images']) for b in boards)}
    if ranking_file is not None:
        # 排名独立于旧sources身份哈希，保留既有浏览器标注与导入文件的兼容性。
        data['ranking'] = validate_ranking(json.loads(ranking_file.read_text(encoding='utf-8')), identity, boards)
        (output / 'ranking.json').write_text(json.dumps(data['ranking'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    template = (PROJECT / 'deploy/moodboard-review/index.html').read_text(encoding='utf-8')
    (output / 'index.html').write_text(template.replace('__COLLECTION_DATA__', payload), encoding='utf-8')
    for file in ('review.css', 'review.js'):
        shutil.copyfile(PROJECT / 'deploy/moodboard-review' / file, output / file)
    manifest = {'schema_version': 'prism.image_rejection_deployment.v1', 'identity': identity,
                'sources': sources, 'board_count': len(boards), 'image_count': data['image_count'],
                'board_image_counts': [len(b['images']) for b in boards], 'originals_recompressed': False,
                'assets': list(assets.records.values())}
    if ranking_file is not None:
        manifest['ranking'] = {'path': 'ranking.json', 'sha256': sha((output / 'ranking.json').read_bytes()),
                               'board_order': [entry['board_id'] for entry in sorted(data['ranking']['entries'], key=lambda item: item['rank'])]}
    manifest['files'] = [{'path': str(file.relative_to(output)), 'sha256': sha(file.read_bytes()), 'bytes': file.stat().st_size}
                         for file in sorted(output.rglob('*')) if file.is_file()]
    (output / 'deployment-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {key: manifest[key] for key in ('identity', 'board_count', 'image_count', 'board_image_counts')} | {'unique_assets': len(assets.records)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ppt', type=Path, default=PROJECT / 'ref/老师对接/情绪板_5版_可编辑复建.pptx')
    parser.add_argument('--output', type=Path, required=True, help='不存在的新静态发布目录')
    parser.add_argument('--ranking', type=Path, help='当前集合的全量排名JSON；不提供时保持原来源顺序')
    args = parser.parse_args()
    print(json.dumps(publish(args.ppt, args.output, args.ranking), ensure_ascii=False, indent=2))

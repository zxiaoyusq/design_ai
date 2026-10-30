"""为已发布图板添加作者切换入口，按原字节外置老师页面的内嵌图片。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from publish_visual_completion import EXTENSIONS, IMAGE


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_page(path: Path, content: bytes) -> None:
    """先写完整临时文件再替换，避免公开页面在写入期间被请求到半份内容。"""
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(content)
    temporary.replace(path)


def publish(teacher: Path, output: Path) -> dict:
    """保留当前首页为 zhangxiaoyu.html；重跑时复用该副本，不把切换入口当作原页面。"""
    current = output / 'index.html'
    original = output / 'zhangxiaoyu.html'
    template = Path(__file__).resolve().parents[2] / 'deploy/visual-comparison.html'
    if not current.is_file():
        raise ValueError('输出目录必须是已发布的图板目录，并包含 index.html')
    current_bytes = current.read_bytes()
    if original.exists():
        if b'id="panel-zhangxiaoyu"' not in current_bytes:
            raise ValueError('当前入口不是已发布切换页，请先核对 zhangxiaoyu.html 副本')
        original_bytes = original.read_bytes()
    else:
        if b'id="panel-zhangxiaoyu"' in current_bytes:
            raise ValueError('切换入口缺少 zhangxiaoyu.html 原页面，无法继续发布')
        original_bytes = current_bytes

    teacher_bytes = teacher.read_bytes()
    assets = {}

    def external_image(match) -> str:
        content = base64.b64decode(match[2], validate=True)
        digest = sha256(content)
        relative = f'guojianfei-assets/{digest}.{EXTENSIONS[match[1]]}'
        assets[relative] = content
        return relative

    teacher_html, occurrences = IMAGE.subn(external_image, teacher_bytes.decode('utf-8'))
    if not occurrences:
        raise ValueError('老师页面中未发现可外置的内嵌图片，请核对源文件')
    if 'data:image/' in teacher_html:
        raise ValueError('老师页面包含未支持的内嵌图片格式')

    # 仅图片地址改变；布局、取景样式、说明、来源链接和原有交互都沿用老师页面。
    (output / 'guojianfei-assets').mkdir(exist_ok=True)
    for relative, content in assets.items():
        write_page(output / relative, content)
    write_page(original, original_bytes)
    write_page(output / 'guojianfei.html', teacher_html.encode('utf-8'))
    wrapper = template.read_bytes()
    manifest = {
        'entry': 'index.html',
        'default_author': 'zhangxiaoyu',
        'entry_sha256': sha256(wrapper),
        'authors': {
            'zhangxiaoyu': {'page': original.name, 'source_sha256': sha256(original_bytes)},
            'guojianfei': {
                'page': 'guojianfei.html',
                'source_name': teacher.name,
                'source_sha256': sha256(teacher_bytes),
                'page_sha256': sha256(teacher_html.encode('utf-8')),
                'image_occurrences': occurrences,
                'unique_image_count': len(assets),
                'assets': [
                    {'path': relative, 'sha256': sha256(content), 'bytes': len(content)}
                    for relative, content in assets.items()
                ],
            },
        },
        'source_images_recompressed': False,
    }
    write_page(output / 'comparison-manifest.json',
               (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    # 子页面与资源全部就位后最后更新入口；已有站点无需重启。
    write_page(current, wrapper)
    deployment = output / 'deployment-manifest.json'
    if deployment.exists():
        data = json.loads(deployment.read_text(encoding='utf-8'))
        data['comparison_manifest'] = 'comparison-manifest.json'
        data['public_files'] = [
            {'path': str(file.relative_to(output)), 'sha256': sha256(file.read_bytes()),
             'bytes': file.stat().st_size}
            for file in sorted(output.rglob('*'))
            if file.is_file() and file != deployment
        ]
        write_page(deployment, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    return {key: value for key, value in manifest.items() if key != 'authors'} | {
        'teacher_unique_images': len(assets), 'original_page_sha256': sha256(original_bytes),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('teacher', type=Path, help='老师的实际试板与取景 HTML')
    parser.add_argument('output', type=Path, help='已有发布图板目录')
    args = parser.parse_args()
    print(json.dumps(publish(args.teacher, args.output), ensure_ascii=False, indent=2))

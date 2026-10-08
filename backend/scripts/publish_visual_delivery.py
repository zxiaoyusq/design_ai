"""将离线视觉交付页发布到站点静态目录，原图字节和审阅结果保持不变。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html as html_module
import json
from pathlib import Path
import re


def publish(source: Path, output: Path, status_url: str | None = None) -> dict:
    """仅替换内嵌图片地址；按原图 SHA 校验，页面最后写入供站点使用。"""
    html = source.read_text(encoding="utf-8")
    block = re.search(
        r'(<script\b[^>]*\bid="assets-data"[^>]*>)(.*?)(</script>)',
        html,
        re.DOTALL,
    )
    if block is None:
        raise ValueError("交付页面缺少 assets-data 图片索引")
    assets = json.loads(block.group(2))
    # 先验证全部原图，避免无效输入发布出一份只包含部分图片的页面。
    verified = []
    extensions = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    for sha, data_url in assets.items():
        match = re.fullmatch(r"data:(image/[a-z]+);base64,(.+)", data_url)
        if match is None or match.group(1) not in extensions:
            raise ValueError(f"不支持的内嵌图片格式：{sha}")
        content = base64.b64decode(match.group(2), validate=True)
        if hashlib.sha256(content).hexdigest() != sha:
            raise ValueError(f"原图 SHA256 不一致：{sha}")
        verified.append((sha, f"assets/{sha}.{extensions[match.group(1)]}", content))

    (output / "assets").mkdir(parents=True, exist_ok=True)
    urls = {}
    for sha, relative_path, content in verified:
        (output / relative_path).write_bytes(content)
        urls[sha] = relative_path
    # 相对地址使页面在当前域名和静态构建产物中使用同一份资源布局。
    html = html[:block.start(2)] + json.dumps(urls) + html[block.end(2):]
    if status_url:
        # 运行中提示只添加到发布副本，不改变封存交付或其中的历史审阅状态。
        notice = (
            '<aside id="expanded-run-notice" style="padding:12px 24px;'
            'background:#fff2ca;color:#3d4a30;font:15px/1.6 system-ui">'
            '新版全库 DNA 筛选与品质复核正在进行。'
            f'<a href="{html_module.escape(status_url, quote=True)}" '
            'style="margin-left:12px;color:#246647">查看本轮进度</a>'
            '；下方是封存的初轮结果。</aside>'
        )
        html, inserted = re.subn(r"(<body\b[^>]*>)", lambda match: match.group(1) + notice,
                                html, count=1)
        if inserted != 1:
            raise ValueError("页面缺少 body，无法添加运行中提示")
    temporary = output / "index.html.tmp"
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output / "index.html")
    manifest = {
        "source": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "page_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "page_bytes": len(html.encode("utf-8")),
        "image_count": len(urls),
        "image_bytes": sum(len(content) for _, _, content in verified),
        "status_url": status_url,
        "assets": urls,
    }
    (output / "deployment-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="离线交付 index.html")
    parser.add_argument("output", type=Path, help="站点 public 下的发布目录")
    parser.add_argument("--status-url", help="可选的新运行进度页地址，标明当前展示的是初轮结果")
    args = parser.parse_args()
    result = publish(args.source, args.output, args.status_url)
    print(json.dumps({key: value for key, value in result.items() if key != "assets"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

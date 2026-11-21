"""趋势文章 Excel 增量预览与入库。"""

from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import hashlib
from io import BytesIO
import json
import re
from typing import BinaryIO
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import BadZipFile, ZipFile
from zlib import error as ZipReadError

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.services.article_trends.catalog import ArticleCatalog, article_from_excel, safe_url
from app.services.dna.storage import _atomic_write


MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_WORKBOOK_BYTES = 160 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 64
ARTICLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


class WorkbookError(ValueError):
    """可直接展示的表格校验错误。"""


@dataclass
class ParsedWorkbook:
    filename: str
    sha256: str
    sheet: str
    articles: list[dict]
    invalid_count: int
    issues: list[dict]


def _read_sheet(workbook):
    sheet = workbook["导出结果"] if "导出结果" in workbook.sheetnames else workbook.active
    if sheet is None:
        raise WorkbookError("Excel 中没有可读取的工作表")
    # 来源系统会把实际有多行、多列的导出文件写成 dimension=A1。
    sheet.reset_dimensions()
    rows = sheet.iter_rows(max_col=MAX_COLUMNS, values_only=True)
    headers = [str(value or "").strip().casefold() for value in next(rows, ())]
    fields = [header for header in headers if header]
    if len(set(fields)) != len(fields):
        raise WorkbookError("Excel 表头包含重复列名，请检查第一行")
    if "id" not in fields or not {"title_zh", "title"}.intersection(fields):
        raise WorkbookError("Excel 第一行必须包含 id 和 title_zh 或 title 列")

    articles, issues = [], []
    invalid_count = 0
    for number, values in enumerate(rows, 2):
        if number > MAX_ROWS + 1:
            raise WorkbookError(f"每份 Excel 最多支持 {MAX_ROWS:,} 行文章")
        if not any(value is not None and value != "" for value in values):
            continue
        raw = {key: value for key, value in zip(headers, values) if key}
        article_id = str(raw.get("id") if raw.get("id") is not None else "").strip()
        # 相同 ID 有时在 Excel 中以整数数值而非文本存储。
        if isinstance(raw.get("id"), float) and raw["id"].is_integer():
            article_id = str(int(raw["id"]))
        title = str(raw.get("title_zh") or "").strip() or str(raw.get("title") or "").strip()
        record = article_from_excel({**raw, "id": article_id, "title_zh": title}, number)
        if not ARTICLE_ID.fullmatch(article_id):
            reason = "文章 ID 为空或格式无效"
        elif not title:
            reason = "缺少文章标题"
        elif str(raw.get("release_time") or "").strip() and not record["published_at"]:
            reason = "发布日期无效"
        else:
            # 部分导出行混用单竖线和双竖线，逐个解析并保留原图顺序。
            urls = (safe_url(url) for url in str(raw.get("image_url") or "").split("|"))
            record["image_urls"] = list(dict.fromkeys(url for url in urls if url))
            articles.append(record)
            continue
        invalid_count += 1
        if len(issues) < 10:
            issues.append({"row": number, "reason": reason})
    if not articles and not invalid_count:
        raise WorkbookError("Excel 没有可检查的文章行")
    return sheet.title, articles, invalid_count, issues


def _parse(file: BinaryIO, filename: str) -> ParsedWorkbook:
    # 文件名只用于来源记录，落盘路径由系统生成。
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".xlsx"):
        raise WorkbookError("请选择 .xlsx 格式的 Excel 文件")
    file.seek(0)
    data = file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise WorkbookError("Excel 文件不能超过 32 MB")
    stream = BytesIO(data)
    try:
        with ZipFile(stream) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_WORKBOOK_BYTES:
                raise WorkbookError("Excel 解压后过大，请分成多份文件导入")
        workbook = load_workbook(stream, read_only=True, data_only=True, keep_links=False)
        try:
            sheet, articles, invalid_count, issues = _read_sheet(workbook)
        finally:
            workbook.close()
    except WorkbookError:
        raise
    except (BadZipFile, ZipReadError, InvalidFileException, OSError, SyntaxError,
            KeyError, IndexError, TypeError, ValueError, RuntimeError) as exc:
        raise WorkbookError("无法读取 Excel，请用表格软件另存为有效的 .xlsx 文件后重试") from exc
    return ParsedWorkbook(filename, hashlib.sha256(data).hexdigest(), sheet, articles, invalid_count, issues)


def _url_key(url):
    """只用原文链接去重，来源首页会被多篇文章共用。"""
    if not url:
        return None
    parts = urlsplit(url)
    return parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), parts.query, parts.fragment


def _plan(existing, workbook: ParsedWorkbook):
    known_ids = {article["article_id"] for article in existing}
    known_urls = {key for article in existing if (key := _url_key(article.get("detail_url")))}
    added = []
    for article in workbook.articles:
        aid = article["article_id"]
        url = _url_key(article["detail_url"])
        if aid in known_ids or url in known_urls:
            continue
        added.append(article)
        known_ids.add(aid)
        if url:
            known_urls.add(url)

    latest = sorted(added, key=lambda article: article["published_at"] or "", reverse=True)
    selection = [workbook.sha256, *[article["article_id"] for article in added]]
    return {
        "selection_digest": hashlib.sha256(json.dumps(selection).encode()).hexdigest(),
        "total_rows": len(workbook.articles) + workbook.invalid_count,
        "new_count": len(added),
        "duplicate_count": len(workbook.articles) - len(added),
        "invalid_count": workbook.invalid_count,
        "image_count": sum(len(article["image_urls"]) for article in added),
        "sample_articles": [
            {key: article[key] for key in ("article_id", "title", "published_at")} for article in latest[:5]
        ],
        "issues": workbook.issues,
    }, added


def preview_workbook(catalog: ArticleCatalog, file: BinaryIO, filename: str) -> dict:
    """读取并汇总待新增的行，返回用于二次确认的摘要。"""
    workbook = _parse(file, filename)
    return _plan(catalog.records(), workbook)[0]


def import_workbook(catalog: ArticleCatalog, file: BinaryIO, filename: str, selection_digest: str) -> dict:
    """锁内复核新增范围，再原子写入单个批次，避免并发上传重复文章。"""
    workbook = _parse(file, filename)
    catalog.import_dir.mkdir(parents=True, exist_ok=True)
    with (catalog.import_dir / ".import.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        existing = catalog.records()
        preview, added = _plan(existing, workbook)
        if preview["selection_digest"] != selection_digest:
            raise RuntimeError("文件或文章库已变化，请重新预览后确认")
        if added:
            now = datetime.now(UTC)
            batch = {
                "schema_version": 1,
                "imported_at": now.isoformat(),
                "source": {"filename": workbook.filename, "sha256": workbook.sha256, "sheet": workbook.sheet},
                "articles": added,
            }
            path = catalog.import_dir / f"{now:%Y%m%dT%H%M%S%fZ}-{uuid4().hex}.json"
            _atomic_write(path, (json.dumps(batch, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return {
            "added_count": len(added),
            "duplicate_count": preview["duplicate_count"],
            "invalid_count": preview["invalid_count"],
            "total_articles": len(existing) + len(added),
        }

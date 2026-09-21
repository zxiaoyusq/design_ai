"""只读提取 MySQL 用户调研数据，输出用户、图片 JSON 并下载关联图片。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable
from urllib.parse import urlsplit

from dotenv import dotenv_values
import pymysql

# 兼容直接运行脚本及作为后端包导入，复用已验证的图片下载和原子写入实现。
if __package__:
    from .prepare_trend_data import _atomic_text, download_image
else:
    from prepare_trend_data import _atomic_text, download_image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "user_research_data_v1"
PROFILE_FIELDS = (
    "country", "profession", "age", "using_mobile_phone_prices",
    "using_mobile_phone_brand", "academic_qualification", "purchase_drivers",
    "user_group_tags", "gender", "mobile_function_usage_preferences",
)
AESTHETIC_FIELDS = ("answer_type", "scenario_type", "question_type", "question", "ai_analysis")
DEMAND_FIELDS = ("ai_index", "scenario", "ref_pic")
# 关联方向经源库模型配置和业务 BID 全量匹配确认，不能使用 parent_bid 推测。
TABLES = {
    "users": "transcend_model_id_user_data",
    "aesthetic_research": "transcend_model_id_user_aesthetic_research",
    "demands": "transcend_model_iduserdemands",
    "image_responses": "transcend_model_iduserrefpic",
    "aesthetic_links": "transcend_model_a3v",
    "demand_links": "transcend_model_a3w",
}


def _normalise(value: Any) -> Any:
    """解码 JSON 容器及数据库 JSON 字符串；普通文本保持原样，不猜测字典含义。"""
    if isinstance(value, str) and value.strip().startswith(("[", "{", '"')):
        try:
            decoded = json.loads(value)
            json.dumps(decoded, allow_nan=False)
            return decoded
        except ValueError:
            return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _active(row: dict[str, Any]) -> bool:
    return row.get("delete_flag", 0) in (0, "0", b"\x00")


def _by_bid(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        if not _active(row):
            continue
        bid = str(row.get("bid") or "").strip()
        if not bid or bid in result:
            raise ValueError(f"源数据存在缺失或重复的当前 bid：{bid}")
        result[bid] = row
    return result


def _research_record(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "bid": str(row["bid"]),
        **{field: _normalise(row.get(field)) for field in fields},
    }


def _attachment_urls(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """逐附件校验、按 URL 去重；坏链接不会使同条反馈的其他有效图片丢失。"""
    parsed = _normalise(value)
    if isinstance(parsed, dict):
        parsed = [parsed]
    elif isinstance(parsed, str):
        parsed = [part.strip() for part in parsed.split("||") if part.strip()]
    if not isinstance(parsed, list) or not parsed:
        return [], [{"url": value, "error": "url 不包含可用附件", "attachment_index": None}]
    urls = []
    errors = []
    for index, item in enumerate(parsed, start=1):
        url = item.get("url") if isinstance(item, dict) else item
        try:
            if not isinstance(url, str):
                raise ValueError("附件缺少字符串 url")
            url = url.strip()
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError("附件 url 不是有效 HTTP(S) 地址")
        except ValueError as exc:
            errors.append({"url": url, "error": str(exc), "attachment_index": index})
            continue
        if url not in urls:
            urls.append(url)
    return urls, errors


def build_records(snapshot: dict[str, Any]) -> tuple[list[dict], list[dict], dict]:
    """按有效用户和显式关系整理数据，图片计数按源反馈记录，不按连接结果计数。"""
    source_users = _by_bid(snapshot["users"])
    users = {
        bid: {
            "id": str(row["id"]), "bid": bid, "name": row.get("name"),
            "profile": {field: _normalise(row.get(field)) for field in PROFILE_FIELDS},
            "aesthetic_research": [], "demand_research": [], "image_preferences": [],
        }
        for bid, row in source_users.items()
    }
    diagnostics: dict[str, Any] = {
        "unlinked_aesthetic_research": [], "unlinked_demand_research": [],
        "ignored_relation_count": 0, "duplicate_relation_count": 0,
        "invalid_image_urls": [], "excluded_image_response_count": 0,
        "duplicate_user_image_emotion_groups": [], "other_emotions": {},
        "unresolved_demand_image_references": [],
        "excluded_unmentioned_aesthetic_research_count": 0,
    }
    for source_key, relation_key, output_key, fields in (
        ("aesthetic_research", "aesthetic_links", "aesthetic_research", AESTHETIC_FIELDS),
        ("demands", "demand_links", "demand_research", DEMAND_FIELDS),
    ):
        children = _by_bid(snapshot[source_key])
        # “未提及”表示本条问答没有可用回答，整条排除，不能转入未关联问答。
        excluded_bids = set()
        if source_key == "aesthetic_research":
            excluded_bids = {
                bid for bid, row in children.items()
                if "未提及" in json.dumps(_normalise(row.get("ai_analysis")), ensure_ascii=False)
            }
            diagnostics["excluded_unmentioned_aesthetic_research_count"] = len(excluded_bids)
            children = {bid: row for bid, row in children.items() if bid not in excluded_bids}
        seen_pairs = set()
        assigned = set()
        for relation in snapshot[relation_key]:
            if not _active(relation):
                continue
            user_bid, target_bid = str(relation["source_bid"]), str(relation["target_bid"])
            if target_bid in excluded_bids:
                continue
            if user_bid not in users or target_bid not in children:
                diagnostics["ignored_relation_count"] += 1
                continue
            pair = (user_bid, target_bid)
            if pair in seen_pairs:
                diagnostics["duplicate_relation_count"] += 1
                continue
            seen_pairs.add(pair)
            assigned.add(target_bid)
            users[user_bid][output_key].append(_research_record(children[target_bid], fields))
        diagnostics[f"unlinked_{output_key}"] = [
            {**_research_record(row, fields), "link_status": "no_active_user_relation"}
            for bid, row in children.items() if bid not in assigned
        ]

    images: dict[str, dict[str, Any]] = {}
    code_images: dict[tuple[str, str], set[str]] = defaultdict(set)
    response_groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in _by_bid(snapshot["image_responses"]).values():
        user_bid = str(row.get("id_user_bid") or "")
        emotion = str(row.get("emotion_tag") or "").strip().upper()
        if user_bid not in users or not emotion:
            diagnostics["excluded_image_response_count"] += 1
            continue
        urls, errors = _attachment_urls(row.get("url"))
        for error in errors:
            diagnostics["invalid_image_urls"].append({
                "source_id": str(row["id"]), "source_bid": str(row["bid"]),
                "user_bid": user_bid, **error,
            })
        for url in urls:
            image_id = "image_" + hashlib.sha256(url.encode()).hexdigest()[:24]
            if url not in images:
                images[url] = {
                    "id": image_id, "url": url, "emotion_tag": [],
                    "enjoy_count": 0, "dislike_count": 0, "other_emotion_counts": {},
                    "survey_pic_bids": [], "reference_codes": [], "responses": [],
                    "status": "pending", "local_path": None,
                }
            image = images[url]
            if emotion not in image["emotion_tag"]:
                image["emotion_tag"].append(emotion)
            if emotion in ("ENJOY", "DISLIKE"):
                image[f"{emotion.lower()}_count"] += 1
            else:
                image["other_emotion_counts"][emotion] = image["other_emotion_counts"].get(emotion, 0) + 1
                diagnostics["other_emotions"][emotion] = diagnostics["other_emotions"].get(emotion, 0) + 1
            response = {
                "source_id": str(row["id"]), "source_bid": str(row["bid"]),
                "user_id": users[user_bid]["id"], "user_bid": user_bid, "emotion_tag": emotion,
            }
            image["responses"].append(response)
            users[user_bid]["image_preferences"].append({
                "image_id": image_id, "source_id": response["source_id"],
                "source_bid": response["source_bid"], "emotion_tag": emotion,
                "ref_pic_code": row.get("name"),
            })
            for field, source_value in (("survey_pic_bids", row.get("survey_pic_bid")), ("reference_codes", row.get("name"))):
                if source_value and str(source_value) not in image[field]:
                    image[field].append(str(source_value))
            if row.get("name"):
                code_images[(user_bid, str(row["name"]).strip())].add(image_id)
            response_groups[(user_bid, image_id, emotion)].append(str(row["id"]))

    diagnostics["duplicate_user_image_emotion_groups"] = [
        {"user_bid": user_bid, "image_id": image_id, "emotion_tag": emotion, "source_ids": source_ids}
        for (user_bid, image_id, emotion), source_ids in response_groups.items() if len(source_ids) > 1
    ]
    # P20 等图片编码只在同一用户内匹配；无标签的图不在图片表中，引用保留为未匹配。
    for user_bid, user in users.items():
        for demand in user["demand_research"]:
            ref_pic = demand["ref_pic"]
            codes = list(dict.fromkeys(re.split(r"[,，、;；\s]+", ref_pic.strip()))) if isinstance(ref_pic, str) and ref_pic.strip() not in ("", "无") else []
            demand["ref_pic_links"] = []
            for code in codes:
                if not code:
                    continue
                matched = sorted(code_images.get((user_bid, code), set()))
                status = "matched" if len(matched) == 1 else "ambiguous" if matched else "unmatched"
                demand["ref_pic_links"].append({"code": code, "image_ids": matched, "status": status})
                if status != "matched":
                    diagnostics["unresolved_demand_image_references"].append({
                        "user_bid": user_bid, "demand_bid": demand["bid"], "code": code, "status": status,
                    })
    return list(users.values()), list(images.values()), diagnostics


def download_research_image(
    image: dict[str, Any], output_dir: Path, timeout: float = 30,
    retries: int = 2, max_bytes: int = 50 * 1024 * 1024,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """复用趋势下载器，按稳定图片 ID 存储，并保持用户调研输出的字段语义。"""
    result = download_image({
        "image_id": image["id"], "trend_id": image["id"], "index": 1,
        "url": image["url"], "status": "pending", "local_path": None,
    }, output_dir, timeout, retries, max_bytes, opener=opener)
    return {**image, **{key: value for key, value in result.items() if key not in ("trend_id", "index", "image_id")}}


def fetch_source(
    env_file: Path, host: str = "10.205.244.130", port: int = 3306,
    database: str = "tim_configcenter_pro",
) -> dict[str, Any]:
    """在同一只读一致性快照中读取白名单字段，导出凭据从不进入数据或日志。"""
    config = dotenv_values(env_file)
    if not config.get("USRDB_NAME") or not config.get("USRDB_PASS"):
        raise ValueError("凭据文件缺少 USRDB_NAME 或 USRDB_PASS")
    connection = pymysql.connect(
        host=host, port=port, user=config["USRDB_NAME"], password=config["USRDB_PASS"],
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10, read_timeout=60, write_timeout=10, autocommit=False,
    )
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "host": host, "port": port, "database": database, "tables": TABLES,
            "fetched_at": datetime.now(UTC).isoformat(), "query_version": "user_research_queries_v2",
            "transaction": "REPEATABLE READ, READ ONLY, WITH CONSISTENT SNAPSHOT",
            "image_response_scope": "nondeleted_users_and_nonempty_emotion_tag",
        },
    }
    fields = {
        "users": ("id", "bid", "delete_flag", "name", *PROFILE_FIELDS),
        "aesthetic_research": ("id", "bid", "delete_flag", *AESTHETIC_FIELDS),
        "demands": ("id", "bid", "delete_flag", *DEMAND_FIELDS),
        "image_responses": ("id", "bid", "delete_flag", "id_user_bid", "survey_pic_bid", "name", "url", "emotion_tag"),
        "aesthetic_links": ("id", "source_bid", "target_bid", "delete_flag"),
        "demand_links": ("id", "source_bid", "target_bid", "delete_flag"),
    }
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            for key, table in TABLES.items():
                # 表名和字段均为程序内常量；命令行输入只能传给连接参数，不能拼入 SQL。
                selected = ", ".join(f"r.{field}" for field in fields[key])
                query = f"SELECT {selected} FROM {table} r WHERE r.delete_flag=0"
                parameters: tuple = ()
                if key == "image_responses":
                    query += (
                        " AND NULLIF(TRIM(r.emotion_tag), %s) IS NOT NULL"
                        " AND EXISTS (SELECT 1 FROM transcend_model_id_user_data u"
                        " WHERE u.bid=r.id_user_bid AND u.delete_flag=0)"
                    )
                    parameters = ("",)
                cursor.execute(query + " ORDER BY r.id", parameters)
                snapshot[key] = cursor.fetchall()
            cursor.execute(
                "SELECT COUNT(*) AS count FROM transcend_model_iduserrefpic"
                " WHERE delete_flag=0 AND NULLIF(TRIM(emotion_tag), %s) IS NOT NULL", ("",),
            )
            all_image_responses = cursor.fetchone()["count"]
            snapshot["scope_stats"] = {
                "nonempty_image_responses_before_user_filter": all_image_responses,
                "excluded_user_image_responses": all_image_responses - len(snapshot["image_responses"]),
            }
    finally:
        # 下载期间不持有数据库事务；即使读取或解析失败也不会提交任何业务写入。
        try:
            connection.rollback()
        finally:
            connection.close()
    return snapshot


def fetch_user_names(
    env_file: Path, host: str = "10.205.244.130", port: int = 3306,
    database: str = "tim_configcenter_pro",
) -> list[dict[str, Any]]:
    """仅查询有效用户的身份键与姓名，供旧快照定向刷新，不读取其他变化。"""
    config = dotenv_values(env_file)
    if not config.get("USRDB_NAME") or not config.get("USRDB_PASS"):
        raise ValueError("凭据文件缺少 USRDB_NAME 或 USRDB_PASS")
    connection = pymysql.connect(
        host=host, port=port, user=config["USRDB_NAME"], password=config["USRDB_PASS"],
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10, read_timeout=60, write_timeout=10, autocommit=False,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            cursor.execute(
                "SELECT id, bid, name FROM transcend_model_id_user_data"
                " WHERE delete_flag=0 ORDER BY id"
            )
            return cursor.fetchall()
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def merge_user_names(snapshot: dict[str, Any], current_users: list[dict[str, Any]]) -> None:
    """只改同一用户的姓名；用户集合不一致时拒绝混合不同时间的快照。"""
    identity = lambda row: (str(row["id"]), str(row["bid"]))
    original = {identity(row): row for row in snapshot["users"] if _active(row)}
    refreshed = {identity(row): row for row in current_users}
    if (len(original) != sum(_active(row) for row in snapshot["users"])
            or len(refreshed) != len(current_users) or original.keys() != refreshed.keys()):
        raise ValueError("源库与旧快照的有效用户 ID/BID 不一致，不能只同步用户名")
    for key, row in original.items():
        row["name"] = refreshed[key]["name"]
    # 其他白名单表仍属于原快照；姓名来源时间单独记录，避免误称整批资料已刷新。
    snapshot.setdefault("source", {})["user_name_sync"] = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "table": TABLES["users"], "query_version": "user_names_v1",
    }


def _dumps(value: Any, *, pretty: bool = False) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2 if pretty else None, allow_nan=False, default=_normalise)


def _counts(users: list[dict], images: list[dict], diagnostics: dict) -> dict[str, int]:
    return {
        "users": len(users),
        "aesthetic_research": sum(len(user["aesthetic_research"]) for user in users),
        "demand_research": sum(len(user["demand_research"]) for user in users),
        "unlinked_aesthetic_research": len(diagnostics["unlinked_aesthetic_research"]),
        "unlinked_demand_research": len(diagnostics["unlinked_demand_research"]),
        "images": len(images), "image_response_assignments": sum(len(image["responses"]) for image in images),
        "enjoy": sum(image["enjoy_count"] for image in images),
        "dislike": sum(image["dislike_count"] for image in images),
        "downloaded": sum(image["status"] == "downloaded" for image in images),
        "failed": sum(image["status"] == "failed" for image in images),
        "pending": sum(image["status"] == "pending" for image in images),
        "cached": sum(bool(image.get("cached")) for image in images),
        "invalid_image_urls": len(diagnostics["invalid_image_urls"]),
    }


def write_outputs(
    output_dir: Path, users: list[dict], images: list[dict], diagnostics: dict, source: dict,
) -> dict[str, int]:
    """两份主 JSON 共用源快照，用户内图片引用同步本地路径，孤立需求显式保留。"""
    image_paths = {image["id"]: image["local_path"] for image in images}
    for user in users:
        for preference in user["image_preferences"]:
            preference["local_path"] = image_paths[preference["image_id"]]
        for demand in user["demand_research"]:
            for link in demand["ref_pic_links"]:
                link["local_paths"] = [image_paths[image_id] for image_id in link["image_ids"]]
    counts = _counts(users, images, diagnostics)
    metadata = {
        "schema_version": SCHEMA_VERSION, "generated_at": datetime.now(UTC).isoformat(),
        "source": source, "local_path_base": ".", "counts": counts,
    }
    _atomic_text(output_dir / "users.json", _dumps({
        **metadata, "users": users,
        "unlinked_aesthetic_research": diagnostics["unlinked_aesthetic_research"],
        "unlinked_demand_research": diagnostics["unlinked_demand_research"],
    }, pretty=True) + "\n")
    _atomic_text(output_dir / "images.json", _dumps({**metadata, "images": images}, pretty=True) + "\n")
    for filename, records in (("users.jsonl", users), ("images.jsonl", images)):
        _atomic_text(output_dir / filename, "".join(_dumps(record) + "\n" for record in records))
    _atomic_text(output_dir / "export_report.json", _dumps({
        **metadata,
        "diagnostics": diagnostics,
        "download_failures": [
            {key: image.get(key) for key in ("id", "url", "local_path", "error", "http_status", "attempts")}
            for image in images if image["status"] == "failed"
        ],
    }, pretty=True) + "\n")
    return counts


def main(argv: list[str] | None = None) -> int:
    """显式运行即开始本地导出；dry-run 只读核对，输入快照可离线复现同一批数据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / "backend" / ".env")
    parser.add_argument("--host", default="10.205.244.130")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--database", default="tim_configcenter_pro")
    parser.add_argument("--input-snapshot", type=Path, help="使用已导出的 source_snapshot.json；仅配合 --refresh-user-names 时连接数据库")
    parser.add_argument("--refresh-user-names", action="store_true",
                        help="与 --input-snapshot 合用：只从数据库更新同一批用户的姓名，保留其他旧快照资料")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "userreseach_data")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-image-mb", type=int, default=50)
    parser.add_argument("--resolve", action="append", default=[], metavar="HOST=IP", help="仅本次下载使用已核实的域名解析地址，可重复传入；不改变原 URL 或证书校验")
    parser.add_argument("--dry-run", action="store_true", help="只检查数据与关联，不下载或写文件")
    args = parser.parse_args(argv)
    if args.refresh_user_names and not args.input_snapshot:
        parser.error("--refresh-user-names 须与 --input-snapshot 合用")
    if args.workers < 1 or args.timeout <= 0 or args.retries < 0 or args.max_image_mb < 1:
        parser.error("workers、timeout、max-image-mb 必须大于 0，retries 必须不小于 0")
    resolutions = {}
    opener = None
    if args.resolve:
        if __package__:
            from .image_transport import create_resolved_opener
        else:
            from image_transport import create_resolved_opener
        for item in args.resolve:
            host, separator, address = item.partition("=")
            if not separator:
                parser.error("resolve 参数格式必须为 HOST=IP")
            resolutions[host] = address
        try:
            opener = create_resolved_opener(resolutions)
        except ValueError as exc:
            parser.error(str(exc))
    if args.input_snapshot:
        snapshot_text = args.input_snapshot.read_text(encoding="utf-8")
        snapshot = json.loads(snapshot_text)
        if args.refresh_user_names:
            try:
                current_users = fetch_user_names(args.env_file, args.host, args.port, args.database)
            except pymysql.MySQLError as exc:
                print(f"数据库连接或读取失败（错误码 {exc.args[0] if exc.args else 'unknown'}）", file=sys.stderr)
                return 1
            merge_user_names(snapshot, current_users)
            snapshot["source"]["user_name_sync"].update({
                "host": args.host, "port": args.port, "database": args.database,
            })
            snapshot_text = _dumps(snapshot, pretty=True) + "\n"
    else:
        try:
            snapshot = fetch_source(args.env_file, args.host, args.port, args.database)
        except pymysql.MySQLError as exc:
            # 驱动错误可能含账户信息，不回显连接串或完整异常。
            print(f"数据库连接或读取失败（错误码 {exc.args[0] if exc.args else 'unknown'}）", file=sys.stderr)
            return 1
        snapshot_text = _dumps(snapshot, pretty=True) + "\n"
    users, images, diagnostics = build_records(snapshot)
    counts = _counts(users, images, diagnostics)
    print(f"用户 {counts['users']}；问答 {counts['aesthetic_research']}；需求 {counts['demand_research']}；未关联需求 {counts['unlinked_demand_research']}；图片 {counts['images']}；ENJOY {counts['enjoy']} / DISLIKE {counts['dislike']}", flush=True)
    if args.dry_run:
        return 0
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "images").mkdir(exist_ok=True)
    _atomic_text(output_dir / "source_snapshot.json", snapshot_text)
    source = {
        **snapshot.get("source", {}), "snapshot_file": "source_snapshot.json",
        "snapshot_sha256": hashlib.sha256(snapshot_text.encode()).hexdigest(),
        "source_counts": {key: len(snapshot[key]) for key in TABLES},
        "scope_stats": snapshot.get("scope_stats", {}),
        "download_dns_overrides": resolutions,
    }
    documentation = PROJECT_ROOT / "docs" / "USER_RESEARCH_DATA.md"
    if documentation.is_file():
        _atomic_text(output_dir / "README.md", documentation.read_text(encoding="utf-8"))
    write_outputs(output_dir, users, images, diagnostics, source)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {
            executor.submit(download_research_image, image, output_dir, args.timeout, args.retries, args.max_image_mb * 1024 * 1024, opener): image
            for image in images
        }
        for completed, future in enumerate(as_completed(jobs), start=1):
            jobs[future].update(future.result())
            if completed % 100 == 0 or completed == len(images):
                counts = write_outputs(output_dir, users, images, diagnostics, source)
                print(f"图片 {completed}/{len(images)}：成功 {counts['downloaded']}，失败 {counts['failed']}，复用 {counts['cached']}", flush=True)
    counts = write_outputs(output_dir, users, images, diagnostics, source)
    print(f"已保存用户信息与图片信息：{output_dir}", flush=True)
    return 2 if counts["failed"] or counts["invalid_image_urls"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

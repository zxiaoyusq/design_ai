#!/usr/bin/env python3
"""Host-side helper that validates and saves a design DNA result."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from validate_output import validate_semantics


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_ROOT.parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "result"
DEFAULT_SCHEMA = SKILL_ROOT / "schemas" / "design-dna-output.schema.json"
DEFAULT_KNOWLEDGE_BASE = SKILL_ROOT / "references" / "design-dna-knowledge-base.zh-CN.md"
DEFAULT_STYLE_REGISTRY = SKILL_ROOT / "references" / "style-registry.json"
DEFAULT_FIELD_REGISTRY = SKILL_ROOT / "references" / "field-registry.json"
DEFAULT_TAG_RELATIONS = SKILL_ROOT / "references" / "tag-relations.json"
DEFAULT_TIMEZONE = "Asia/Shanghai"
TIMESTAMP_PATTERN = re.compile(r"^\d{8}_\d{6}$")


def _reject_nonfinite_constant(value: str) -> Any:
    """保存入口只接受标准 JSON 数字。"""
    raise ValueError(f"不允许非有限数值 {value!r}")


def _strict_json_loads(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_nonfinite_constant)


def _load_json_source(source: str) -> dict[str, Any]:
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8-sig")
        data = _strict_json_loads(text)
    except OSError as exc:
        raise ValueError(f"无法读取结果 JSON：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"结果 JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}") from exc
    except ValueError as exc:
        raise ValueError(f"结果 JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("结果 JSON 根节点必须是对象。")
    return data


def _validate_result(data: dict[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ValueError("缺少 jsonschema；请安装 jsonschema>=4.21,<5。") from exc

    schema = _strict_json_loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )
    errors: list[str] = []
    for error in schema_errors:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"schema {path}: {error.message}")

    warnings: list[str] = []
    # Schema 已否决的畸形结构不再进入语义层，避免保存入口抛出内部异常。
    if not schema_errors:
        knowledge_base = DEFAULT_KNOWLEDGE_BASE.read_text(encoding="utf-8")
        style_registry = _strict_json_loads(DEFAULT_STYLE_REGISTRY.read_text(encoding="utf-8"))
        field_registry = _strict_json_loads(DEFAULT_FIELD_REGISTRY.read_text(encoding="utf-8"))
        tag_relations = _strict_json_loads(DEFAULT_TAG_RELATIONS.read_text(encoding="utf-8"))
        semantic_errors, warnings = validate_semantics(
            data,
            knowledge_base,
            style_registry,
            field_registry,
            tag_relations,
        )
        errors.extend(semantic_errors)
    if errors:
        details = "\n".join(f"- {item}" for item in errors)
        raise ValueError(f"结果未通过校验，未写入文件：\n{details}")
    return warnings


def _safe_image_stem(image: str) -> str:
    raw = unicodedata.normalize("NFKC", Path(image).stem).strip()
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in raw)
    safe = re.sub(r"_+", "_", safe).strip("-_")
    return (safe or "image")[:96]


def _current_timestamp(timezone_name: str) -> str:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"未知时区：{timezone_name}") from exc
    return datetime.now(timezone).strftime("%Y%m%d_%H%M%S")


def _available_output_path(output_dir: Path, base_name: str) -> Path:
    candidate = output_dir / f"{base_name}.json"
    sequence = 2
    while candidate.exists():
        candidate = output_dir / f"{base_name}_{sequence:02d}.json"
        sequence += 1
    return candidate


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(data, temporary_file, ensure_ascii=False, indent=2, allow_nan=False)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
        path.chmod(0o644)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校验设计 DNA 完整结果，并按时间戳与图片名写入 data/result。"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="结果 JSON 文件；省略或使用 - 时从标准输入读取",
    )
    parser.add_argument("--image", required=True, help="原始图片路径或文件名，用于生成输出文件名")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录，默认 {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="文件名时间戳使用的 IANA 时区")
    parser.add_argument(
        "--timestamp",
        help="可选固定时间戳，格式 YYYYMMDD_HHMMSS；主要用于可重复测试",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        data = _load_json_source(args.input)
        warnings = _validate_result(data)
        timestamp = args.timestamp or _current_timestamp(args.timezone)
        if not TIMESTAMP_PATTERN.fullmatch(timestamp):
            raise ValueError("--timestamp 必须使用 YYYYMMDD_HHMMSS 格式。")
        image_stem = _safe_image_stem(args.image)
        output_dir = args.output_dir.expanduser().resolve()
        output_path = _available_output_path(
            output_dir,
            f"{timestamp}_{image_stem}_design_dna",
        )
        _atomic_write_json(output_path, data)
        for warning in warnings:
            print(f"警告：{warning}", file=sys.stderr)
        print(output_path)
        return 0
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""不依赖数据库的图片与 DNA 结果文件存储。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError


PROJECT_ROOT = Path(__file__).resolve().parents[4]
UPLOADS_DIR = PROJECT_ROOT / "data" / "uploads"
RESULTS_DIR = PROJECT_ROOT / "data" / "result"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_FORMATS = {
    "GIF": (".gif", "image/gif"),
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}
RESULT_ID_PATTERN = re.compile(r"^[\w-]+$", re.UNICODE)
BUSINESS_VIEW_SCHEMA_VERSION = "design_dna_business_view_v1.1"


class ImageStorageError(ValueError):
    """上传图片不符合文件约束。"""


@dataclass(frozen=True, slots=True)
class StoredImage:
    """磁盘上的图片及其展示元数据。"""

    id: str
    filename: str
    relative_path: str | None
    content_type: str
    size: int
    created_at: str

    @property
    def preview_url(self) -> str:
        return f"/api/v1/dna/images/{self.id}/content"

    def to_api_dict(self) -> dict[str, Any]:
        return {**asdict(self), "preview_url": self.preview_url}


def _safe_filename(filename: str, extension: str) -> str:
    """保留可读图片名，同时去除路径和危险字符。"""

    raw_stem = unicodedata.normalize("NFKC", Path(filename).stem).strip()
    safe_stem = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in raw_stem
    )
    safe_stem = re.sub(r"_+", "_", safe_stem).strip("-_") or "image"
    return f"{safe_stem[:96]}{extension}"


def _validated_image(data: bytes) -> tuple[str, str]:
    if not data:
        raise ImageStorageError("图片文件为空")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageStorageError("单张图片不能超过 20 MB")

    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            image_format = image.format
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageStorageError("文件不是可读取的图片") from exc

    if image_format not in ALLOWED_FORMATS:
        supported = ", ".join(sorted(ALLOWED_FORMATS))
        raise ImageStorageError(f"暂不支持该图片格式，可用格式：{supported}")
    return ALLOWED_FORMATS[image_format]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


async def save_uploaded_image(
    upload: UploadFile,
    relative_path: str | None = None,
) -> StoredImage:
    """校验并保存一张上传图片，返回可持久扫描的元数据。"""

    data = await upload.read(MAX_IMAGE_BYTES + 1)
    extension, content_type = _validated_image(data)
    image_id = uuid4().hex
    filename = _safe_filename(upload.filename or "image", extension)
    image_dir = UPLOADS_DIR / image_id
    image_path = image_dir / filename
    created_at = datetime.now(UTC).isoformat()
    stored = StoredImage(
        id=image_id,
        filename=filename,
        relative_path=relative_path or None,
        content_type=content_type,
        size=len(data),
        created_at=created_at,
    )

    _atomic_write(image_path, data)
    metadata = json.dumps(asdict(stored), ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(image_dir / "metadata.json", metadata + b"\n")
    return stored


def _read_metadata(metadata_path: Path) -> StoredImage | None:
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        return StoredImage(**data)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def list_uploaded_images() -> list[StoredImage]:
    """扫描文件系统，服务重启后仍可恢复已上传图片列表。"""

    if not UPLOADS_DIR.exists():
        return []
    images = [
        stored
        for metadata_path in UPLOADS_DIR.glob("*/metadata.json")
        if (stored := _read_metadata(metadata_path)) is not None
    ]
    return sorted(images, key=lambda image: image.created_at, reverse=True)


def get_uploaded_image(image_id: str) -> tuple[StoredImage, Path]:
    """解析图片 ID，并确保真实文件仍位于对应上传目录。"""

    if not re.fullmatch(r"[a-f0-9]{32}", image_id):
        raise FileNotFoundError("图片不存在")
    image_dir = UPLOADS_DIR / image_id
    stored = _read_metadata(image_dir / "metadata.json")
    if stored is None or stored.id != image_id:
        raise FileNotFoundError("图片不存在")
    image_path = image_dir / stored.filename
    if not image_path.is_file():
        raise FileNotFoundError("图片文件不存在")
    return stored, image_path


def _trace_data(result_id: str) -> dict[str, Any] | None:
    if not RESULT_ID_PATTERN.fullmatch(result_id):
        return None
    path = RESULTS_DIR / ".metadata" / f"{result_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _stored_result_image(result_id: str) -> Path | None:
    if not RESULT_ID_PATTERN.fullmatch(result_id):
        raise FileNotFoundError("结果不存在")
    image_dir = RESULTS_DIR / ".images"
    for extension, _ in ALLOWED_FORMATS.values():
        candidate = image_dir / f"{result_id}{extension}"
        if candidate.is_file():
            return candidate
    return None


def _stored_result_images(result_id: str) -> list[Path]:
    if not RESULT_ID_PATTERN.fullmatch(result_id):
        raise FileNotFoundError("结果不存在")
    image_dir = RESULTS_DIR / ".images"
    return [
        candidate
        for extension, _ in ALLOWED_FORMATS.values()
        if (candidate := image_dir / f"{result_id}{extension}").is_file()
    ]


def save_result_image(result_id: str, image_path: Path) -> Path:
    """保存最长边 480px 的独立缩略图，素材删除后结果仍可正常展示。"""

    if not RESULT_ID_PATTERN.fullmatch(result_id):
        raise ValueError("结果 ID 不合法")
    try:
        data = image_path.read_bytes()
    except OSError as exc:
        raise FileNotFoundError("结果对应图片不存在") from exc
    _validated_image(data)
    try:
        with Image.open(BytesIO(data)) as image:
            image.seek(0)
            thumbnail = ImageOps.exif_transpose(image)
            thumbnail.thumbnail((480, 480))
            has_alpha = "A" in thumbnail.getbands() or "transparency" in thumbnail.info
            thumbnail = thumbnail.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            thumbnail.save(output, format="WEBP", quality=84, method=4)
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageStorageError("无法生成结果缩略图") from exc
    target = RESULTS_DIR / ".images" / f"{result_id}.webp"
    _atomic_write(target, output.getvalue())
    for previous in _stored_result_images(result_id):
        if previous != target:
            previous.unlink(missing_ok=True)
    return target


def _matching_uploaded_image(sha256: str) -> Path | None:
    """旧结果可能没有独立图片，通过追溯哈希从素材库安全恢复。"""

    for stored in list_uploaded_images():
        try:
            _, image_path = get_uploaded_image(stored.id)
            if hashlib.sha256(image_path.read_bytes()).hexdigest() == sha256:
                return image_path
        except (FileNotFoundError, OSError):
            continue
    return None


def get_result_image(result_id: str) -> tuple[Path, str]:
    """读取结果缩略图；旧结果首次读取时从受控素材目录生成独立副本。"""

    _safe_result_path(result_id, ".json")
    image_path = _stored_result_image(result_id)
    if image_path is not None and image_path.suffix.lower() != ".webp":
        image_path = save_result_image(result_id, image_path)
    if image_path is None:
        trace = _trace_data(result_id)
        input_image = trace.get("input_image") if trace else None
        sha256 = input_image.get("sha256") if isinstance(input_image, dict) else None
        if not isinstance(sha256, str):
            raise FileNotFoundError("结果对应图片不存在")
        source = _matching_uploaded_image(sha256)
        if source is None:
            raise FileNotFoundError("结果对应图片不存在")
        image_path = save_result_image(result_id, source)
    _, content_type = _validated_image(image_path.read_bytes())
    return image_path, content_type


def delete_uploaded_image(image_id: str) -> None:
    """删除一项素材；先为引用它的历史结果补齐独立缩略图。"""

    _, image_path = get_uploaded_image(image_id)
    source_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    metadata_dir = RESULTS_DIR / ".metadata"
    if metadata_dir.exists():
        for trace_path in metadata_dir.glob("*.json"):
            if not RESULT_ID_PATTERN.fullmatch(trace_path.stem):
                continue
            trace = _trace_data(trace_path.stem)
            input_image = trace.get("input_image") if trace else None
            trace_sha256 = input_image.get("sha256") if isinstance(input_image, dict) else None
            if trace_sha256 != source_sha256 or _stored_result_image(trace_path.stem) is not None:
                continue
            try:
                _safe_result_path(trace_path.stem, ".json")
                _safe_result_path(trace_path.stem, "_business_view.json")
            except FileNotFoundError:
                continue
            save_result_image(trace_path.stem, image_path)

    image_dir = image_path.parent
    # 上传目录按固定 ID 创建且只允许普通文件，遇到意外子目录时拒绝递归删除。
    children = list(image_dir.iterdir())
    if any(not child.is_file() and not child.is_symlink() for child in children):
        raise ImageStorageError("图片目录包含异常内容，无法安全删除")
    for child in children:
        child.unlink()
    image_dir.rmdir()


def _safe_result_path(result_id: str, suffix: str) -> Path:
    if not RESULT_ID_PATTERN.fullmatch(result_id):
        raise FileNotFoundError("结果不存在")
    path = RESULTS_DIR / f"{result_id}{suffix}"
    if not path.is_file():
        raise FileNotFoundError("结果不存在")
    return path


def load_result(result_id: str, view: str) -> dict[str, Any]:
    """读取业务视图或完整结果，路径不能由请求方任意拼接。"""

    suffix = "_business_view.json" if view == "business" else ".json"
    path = _safe_result_path(result_id, suffix)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"结果文件不可读取：{path.name}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"结果文件根节点不是对象：{path.name}")
    if view == "business" and (
        "model_id" not in data
        or data.get("schema_version") != BUSINESS_VIEW_SCHEMA_VERSION
    ):
        data = save_business_view_model(result_id)
    return data


def save_business_view_model(
    result_id: str,
    model_id: str | None = None,
) -> dict[str, Any]:
    """写入业务视图的模型追溯字段，并兼容迁移已有结果。"""

    path = _safe_result_path(result_id, "_business_view.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"结果文件不可读取：{path.name}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"结果文件根节点不是对象：{path.name}")

    resolved_model_id = model_id
    if resolved_model_id is None:
        trace = _trace_data(result_id)
        trace_model_id = trace.get("model_id") if trace else None
        resolved_model_id = trace_model_id if isinstance(trace_model_id, str) else None
    data["schema_version"] = BUSINESS_VIEW_SCHEMA_VERSION
    data["model_id"] = resolved_model_id
    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(path, content + b"\n")
    return data


def delete_result(result_id: str) -> None:
    """删除一条结果的详情、业务视图、追溯信息和独立缩略图。"""

    full_path = _safe_result_path(result_id, ".json")
    business_path = _safe_result_path(result_id, "_business_view.json")
    trace_path = RESULTS_DIR / ".metadata" / f"{result_id}.json"
    image_paths = _stored_result_images(result_id)
    for path in (business_path, full_path, trace_path, *image_paths):
        path.unlink(missing_ok=True)


def save_result_trace(result_id: str, trace: dict[str, Any]) -> Path:
    """保存不影响 Skill Schema 的执行追溯旁路数据。"""

    if not RESULT_ID_PATTERN.fullmatch(result_id):
        raise ValueError("结果 ID 不合法")
    path = RESULTS_DIR / ".metadata" / f"{result_id}.json"
    content = json.dumps(trace, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(path, content + b"\n")
    return path


def _result_image_name(result_id: str) -> str:
    match = re.match(
        r"^\d{8}_\d{6}_(?P<name>.+)_design_dna(?:_\d{2})?$",
        result_id,
    )
    return match.group("name") if match else result_id


def list_results() -> list[dict[str, Any]]:
    """只列出同时具备完整结果和业务视图的成功任务。"""

    if not RESULTS_DIR.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for full_path in RESULTS_DIR.glob("*_design_dna*.json"):
        if full_path.name.endswith("_business_view.json"):
            continue
        result_id = full_path.stem
        business_path = RESULTS_DIR / f"{result_id}_business_view.json"
        if not business_path.is_file():
            continue
        try:
            business = json.loads(business_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        object_view = business.get("object", {}) if isinstance(business, dict) else {}
        style_view = business.get("style", {}) if isinstance(business, dict) else {}
        primary_style = style_view.get("primary") or style_view.get("primary_style")
        if isinstance(primary_style, dict):
            primary_style = primary_style.get("name") or primary_style.get("level_2")
        try:
            get_result_image(result_id)
            preview_url: str | None = f"/api/v1/dna/results/{result_id}/image"
        except (FileNotFoundError, ImageStorageError, OSError):
            preview_url = None
        summaries.append(
            {
                "id": result_id,
                "image_name": _result_image_name(result_id),
                "preview_url": preview_url,
                "created_at": datetime.fromtimestamp(
                    full_path.stat().st_mtime,
                    tz=UTC,
                ),
                "category": object_view.get("category") if isinstance(object_view, dict) else None,
                "primary_style": primary_style if isinstance(primary_style, str) else None,
                "summary": business.get("design_summary") if isinstance(business, dict) else None,
            }
        )
    return sorted(summaries, key=lambda item: item["created_at"], reverse=True)

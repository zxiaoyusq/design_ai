"""打包/恢复独立选图档案；部署不依赖原资料目录，也不会调用模型。"""

import argparse
from datetime import UTC, datetime
import getpass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
COLLECTIONS = ("image_review", "image_review_remaining")
METADATA = ("web_task.json", "state.json", "completion.json", "manifest.json", "sources.json",
            "high_potential_trends.json", "performance_report.json", "report.md", "image_paths.md")


def digest(path):
    with path.open("rb") as stream:
        return sha256_file(stream)


def sha256_file(stream):
    value = sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(block)
    return value.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def crypt(source, target, password, *, decrypt=False):
    """密码通过标准输入交给 OpenSSL，不进入命令参数、清单或日志。"""
    command = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256",
               "-in", str(source), "-out", str(target), "-pass", "stdin"]
    if decrypt:
        command.append("-d")
    subprocess.run(command, input=password + "\n", text=True, check=True, capture_output=True)


def pack(root, task_id, output, tag, password=None, part_bytes=400 * 1024 * 1024):
    """只冻结当前可选图片及来源；不打包缩略图、旧导出、密钥或无关研究任务。"""
    if not re.fullmatch(r"web_[a-f0-9]{32}", task_id):
        raise ValueError("任务编号不合法")
    if password is not None and not password.strip():
        raise ValueError("附件密码不能为空")
    run = root / "data/result/high_trend" / task_id
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": "image_review_bundle.v1", "task_id": task_id,
                "created_at": datetime.now(UTC).isoformat(), "repository": "zxiaoyusq/design_ai",
                "release_tag": tag, "encrypted": password is not None,
                "collections": {}, "files": [], "assets": []}
    with TemporaryDirectory(prefix="image-review-snapshot-") as temp:
        snapshot = Path(temp)
        inputs = []
        for filename in METADATA:
            path = run / filename
            if path.is_file():
                frozen = snapshot / filename
                frozen.write_bytes(path.read_bytes())
                inputs.append((filename, frozen, None))
        for collection in COLLECTIONS:
            # 原子保存的 review.json 一次读取，后续人工修改不会使本包索引与选择版本混杂。
            review = json.loads((run / collection / "review.json").read_text())
            manifest["collections"][collection] = {"revision": review["revision"],
                "total": len(review["images"]), "retained": sum(i["retained"] for i in review["images"])}
            folder = snapshot / collection
            folder.mkdir()
            frozen = folder / "review.json"
            write_json(frozen, review)
            inputs.append((f"{collection}/review.json", frozen, None))
            for image in review["images"]:
                relative = safe_path(image["copy_path"])
                if relative.parts[0] != "images":
                    raise ValueError("图片副本必须在 images 目录")
                source = (run / collection / relative).resolve()
                if not source.is_relative_to((run / collection / "images").resolve()):
                    raise ValueError("图片副本越界")
                inputs.append((f"{collection}/{relative}", source, image["sha256"]))
        groups, group, size = [], [], 0
        for relative, source, expected in inputs:
            size_now = source.stat().st_size
            if group and size + size_now > part_bytes:
                groups.append(group)
                group, size = [], 0
            checksum = digest(source)
            if expected and checksum != expected:
                raise ValueError(f"图片副本内容已改变：{relative}")
            manifest["files"].append({"path": relative, "size": size_now, "sha256": checksum})
            group.append((relative, source))
            size += size_now
        if group:
            groups.append(group)
        for number, group in enumerate(groups, 1):
            name = f"images-{number:03d}.tar.gz"
            compressed = snapshot / name
            with tarfile.open(compressed, "w:gz", compresslevel=1) as archive:
                for relative, source in group:
                    archive.add(source, arcname=relative, recursive=False)
            target = output / (name + ".enc" if password else name)
            if password:
                crypt(compressed, target, password)
            else:
                shutil.copyfile(compressed, target)
            compressed.unlink()
            manifest["assets"].append({"name": target.name, "size": target.stat().st_size,
                                       "sha256": digest(target)})
            print(f"已打包 {number}/{len(groups)}", flush=True)
    write_json(output / "manifest.json", manifest)
    return manifest


def safe_path(value):
    """仅允许任务目录内的普通相对路径，拒绝路径穿越和平台分隔符绕过。"""
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\\" in value:
        raise ValueError("附件路径不合法")
    return path


def restore(root, manifest, cache, password=None, local_only=False):
    """先完整校验到临时目录，再整体落盘；已有任务绝不被部署覆盖。"""
    if manifest.get("schema_version") != "image_review_bundle.v1":
        raise ValueError("不支持的部署清单版本")
    task_id = manifest["task_id"]
    if not re.fullmatch(r"web_[a-f0-9]{32}", task_id):
        raise ValueError("任务编号不合法")
    parent = root / "data/result/high_trend"
    destination = parent / task_id
    if destination.exists():
        raise FileExistsError(f"任务目录已存在，不覆盖已有选择：{destination}")
    if manifest["encrypted"] and not password:
        raise ValueError("请输入附件解密密码")
    parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    expected = {str(safe_path(item["path"])): item for item in manifest["files"]}
    if len(expected) != len(manifest["files"]):
        raise ValueError("清单有重复文件")
    with TemporaryDirectory(prefix=".image-review-restore-", dir=parent) as temporary:
        staging = Path(temporary) / task_id
        staging.mkdir()
        seen = set()
        for asset in manifest["assets"]:
            name = asset["name"]
            if str(safe_path(name)) != Path(name).name:
                raise ValueError("附件名称不合法")
            source = cache / name
            if not source.is_file() or digest(source) != asset["sha256"]:
                if local_only:
                    raise ValueError(f"附件缺失或校验失败：{name}")
                url = f"https://github.com/{manifest['repository']}/releases/download/{manifest['release_tag']}/{name}"
                partial = source.with_suffix(source.suffix + ".partial")
                print(f"下载 {name}", flush=True)
                with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
                if partial.stat().st_size != asset["size"] or digest(partial) != asset["sha256"]:
                    raise ValueError(f"下载校验失败：{name}")
                partial.replace(source)
            archive_path = source
            if manifest["encrypted"]:
                archive_path = Path(temporary) / "decrypted.tar.gz"
                crypt(source, archive_path, password, decrypt=True)
            with tarfile.open(archive_path, "r:gz") as archive:
                for member in archive:
                    name = str(safe_path(member.name))
                    if not member.isfile() or name not in expected or name in seen:
                        raise ValueError(f"附件含未声明或重复文件：{name}")
                    if member.size != expected[name]["size"]:
                        raise ValueError(f"文件大小不符：{name}")
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as stream, target.open("wb") as out:
                        shutil.copyfileobj(stream, out)
                    if digest(target) != expected[name]["sha256"]:
                        raise ValueError(f"文件校验失败：{name}")
                    seen.add(name)
            if manifest["encrypted"]:
                archive_path.unlink()
            print(f"已校验 {asset['name']}", flush=True)
        if seen != set(expected):
            raise ValueError("部署附件缺少清单中的文件")
        for collection in COLLECTIONS:
            path = staging / collection / "review.json"
            review = json.loads(path.read_text())
            review["folder"] = str(destination / collection)
            write_json(path, review)
        write_json(staging / "image_review_deployment.json", {
            "restored_at": datetime.now(UTC).isoformat(), "release_tag": manifest["release_tag"],
            "collections": manifest["collections"], "note": "原始路径是历史来源；图片通过本机副本读取。"})
        if destination.exists():
            raise FileExistsError("任务目录在恢复期间被创建，未覆盖")
        staging.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["pack", "restore"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=ROOT / "deploy/image-review/manifest.json")
    parser.add_argument("--bundle-dir", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--tag")
    parser.add_argument("--encrypt", action="store_true")
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()
    if args.action == "pack":
        if not (args.task and args.tag and args.bundle_dir):
            parser.error("pack 需要 --task、--tag 和 --bundle-dir")
        password = getpass.getpass("附件密码：") if args.encrypt else None
        pack(args.root.resolve(), args.task, args.bundle_dir, args.tag, password)
    else:
        manifest = json.loads(args.manifest.read_text())
        password = getpass.getpass("附件密码：") if manifest["encrypted"] else None
        cache = args.bundle_dir or args.root / ".runtime/image-review-bundles" / manifest["release_tag"]
        path = restore(args.root.resolve(), manifest, cache, password, args.local_only)
        print(f"恢复完成：{path}\n打开 /high-trends/image-review?task={manifest['task_id']}")


if __name__ == "__main__":
    main()

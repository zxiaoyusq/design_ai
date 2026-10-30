"""离线打包当前两个聚类主 Skill 及明确依赖，保留原文件与逐项 SHA。"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
NAME = "prism-dna-clustering-skills-20261021"
STAGE = ROOT / "data/result/skill_handoffs" / NAME
ARCHIVE = ROOT / "ref/棱镜_DNA提取与图片聚类双Skill_20261021.zip"
SKILLS = ("prism-design-dna-preparation", "prism-dna-cluster-moodboard")
PACKAGES = ("deepagents", "langchain", "langchain-core", "pydantic", "jsonschema", "Pillow")
OMIT = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store", ".env", "auth.json"}

VERIFY = '''"""离线核对交接清单，不启动模型、网络或原项目服务。"""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
errors = []
for row in manifest["files"]:
    path = root / row["path"]
    if not path.resolve().is_relative_to(root) or not path.is_file():
        errors.append(row["path"] + ": missing or outside package")
        continue
    raw = path.read_bytes()
    if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
        errors.append(row["path"] + ": size or SHA mismatch")
print(json.dumps({"checked_files": len(manifest["files"]), "ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(1 if errors else 0)
'''


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    # 固定范围的交接快照不得覆盖既有文件，也不扫描账号或业务结果目录。
    if STAGE.exists() or ARCHIVE.exists():
        raise FileExistsError("交接目标已存在，请保留旧包并选择新版本")
    STAGE.mkdir(parents=True)
    rows = []

    def add_bytes(relative: str, raw: bytes, source: str | None = None) -> None:
        target = STAGE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
        rows.append({"path": relative, "bytes": len(raw), "sha256": sha(raw), "source": source})

    def add_source(path: Path, relative: str | None = None) -> None:
        if path.is_symlink():
            raise ValueError(f"发现未登记软链接：{path.relative_to(ROOT)}")
        name = path.relative_to(ROOT).as_posix()
        add_bytes(relative or name, path.read_bytes(), name)

    def add_tree(relative: str) -> None:
        source = ROOT / relative
        for path in sorted(source.rglob("*")):
            if path.is_file() and not any(part in OMIT for part in path.relative_to(source).parts) and path.suffix not in {".pyc", ".pyo"}:
                add_source(path)

    for skill in SKILLS:
        add_tree(f".agents/skills/{skill}")
    add_tree("ref/multimodal-design-dna-multitag-extractor/references")
    for relative in (
        "backend/app/services/visual_workflow/codex_transport.py",
        "ref/参考情绪版/20261010-015937.jpeg",
        "ref/参考情绪版/20261010-015957.jpeg",
        "ref/参考情绪版/screenshot-20261010-015930.png",
        "ref/参考情绪版/img_v3_0216b_b557ea20-5a93-49a6-8816-0d5c1896eafg.jpg",
        "ref/问题反馈/三个情绪版_问题圈注.html",
    ):
        add_source(ROOT / relative)
    add_source(ROOT / "docs/handoffs/dna-clustering-skills-20261021.html", "index.html")
    add_source(Path(__file__), "packaging/package_dna_clustering_skills.py")
    versions = {name: importlib.metadata.version(name) for name in PACKAGES}
    add_bytes("runtime-versions.json", (json.dumps({"python": sys.version.split()[0], "packages": versions,
        "scope": "打包环境直接依赖快照；非完整传递依赖锁文件，接收环境需另行安装和验证。"}, ensure_ascii=False, indent=2) + "\n").encode())
    add_bytes("requirements-runtime.txt", ("# 打包时当前环境直接依赖；可选浏览器截图另需 Node.js/Playwright/Chromium。\n" +
        "\n".join(f"{name}=={version}" for name, version in versions.items()) + "\n").encode())
    add_bytes("verify_package.py", VERIFY.encode())
    add_bytes("先读我.txt", ("请先打开 index.html。\n两个主入口位于 .agents/skills/；该目录以点开头，在部分文件管理器中默认隐藏。\n"
        "保持目录层级；支持依赖、四张图例和反馈原件已附。原图库、历史DNA/回执、账号凭证未附。\n"
        "校验：python verify_package.py。打包不会运行提取或聚类。\n").encode())
    manifest = {"schema_version": "prism.two_skill_handoff.v1", "handoff_date": "2026-10-21", "timezone": "Asia/Shanghai",
        "skills": [{"name": SKILLS[0], "version": "0.4.1"}, {"name": SKILLS[1], "version": "0.13.0"}],
        "source_files_modified": False, "pipeline_model_calls": 0, "files": rows}
    (STAGE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 再核源字节，防止打包过程中源文件发生变化却形成混合版本。
    for row in rows:
        if row["source"] and sha((ROOT / row["source"]).read_bytes()) != row["sha256"]:
            raise ValueError(f"打包期间源文件变化：{row['source']}")
    with zipfile.ZipFile(ARCHIVE, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(STAGE.rglob("*")):
            if path.is_file():
                archive.write(path, f"{NAME}/{path.relative_to(STAGE).as_posix()}")
    with zipfile.ZipFile(ARCHIVE) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC校验失败")
        for row in rows:
            if sha(archive.read(f"{NAME}/{row['path']}")) != row["sha256"]:
                raise ValueError(f"ZIP内SHA不一致：{row['path']}")
    digest = sha(ARCHIVE.read_bytes())
    ARCHIVE.with_suffix(".zip.sha256").write_text(digest + "  " + ARCHIVE.name + "\n", encoding="utf-8")
    print(json.dumps({"zip": str(ARCHIVE), "html": str(STAGE / "index.html"), "files": len(rows) + 1,
        "bytes": ARCHIVE.stat().st_size, "sha256": digest, "crc_and_file_sha_verified": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

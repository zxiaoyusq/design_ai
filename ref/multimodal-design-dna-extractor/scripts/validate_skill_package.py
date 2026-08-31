#!/usr/bin/env python3
"""Lightweight self-check for the Agent Skill package."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "SKILL.md",
    "manifest.json",
    "references/extraction-protocol.zh-CN.md",
    "references/output-contract.zh-CN.md",
    "references/design-dna-knowledge-base.zh-CN.md",
    "schemas/design-dna-output.schema.json",
    "scripts/validate_output.py",
    "scripts/save_result.py",
]


def main() -> int:
    errors: list[str] = []
    for rel in REQUIRED:
        if not (ROOT / rel).is_file():
            errors.append(f"missing required file: {rel}")

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", skill, re.S)
    if not match:
        errors.append("SKILL.md missing YAML frontmatter")
    else:
        front = match.group(1)
        name_match = re.search(r"^name:\s*(.+)$", front, re.M)
        desc_match = re.search(r"^description:\s*(.+)$", front, re.M)
        if not name_match:
            errors.append("frontmatter missing name")
        else:
            name = name_match.group(1).strip().strip('"\'')
            if name != ROOT.name:
                errors.append(f"frontmatter name {name!r} must match directory {ROOT.name!r}")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
                errors.append("frontmatter name violates Agent Skills naming constraints")
        if not desc_match or not desc_match.group(1).strip():
            errors.append("frontmatter missing non-empty description")
        elif len(desc_match.group(1).strip()) > 1024:
            errors.append("frontmatter description exceeds 1024 characters")

    for rel in ["manifest.json", "schemas/design-dna-output.schema.json"]:
        try:
            json.loads((ROOT / rel).read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON in {rel}: {exc}")

    if not errors:
        for example in sorted((ROOT / "examples").glob("*.json")):
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "validate_output.py"), str(example)],
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                errors.append(f"example failed validation: {example.name}\n{proc.stdout}{proc.stderr}")

    if errors:
        print(f"INVALID PACKAGE: {len(errors)} error(s)")
        for error in errors:
            print(f"  ERROR: {error}")
        return 1
    print("VALID PACKAGE: structure, metadata, schema, and examples passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

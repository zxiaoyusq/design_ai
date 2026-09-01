#!/usr/bin/env python3
"""从最终 Schema 生成不含 Python 派生字段的模型输出 Schema。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FINAL_SCHEMA = ROOT / "schemas" / "design-dna-output.schema.json"
DEFAULT_OUTPUT = ROOT / "schemas" / "design-dna-model-output.schema.json"


def _render() -> str:
    schema: dict[str, Any] = json.loads(FINAL_SCHEMA.read_text(encoding="utf-8"))
    schema["$id"] = "https://example.internal/schemas/design-dna-multitag-model-output-v1.1.json"
    schema["title"] = "Multimodal Design DNA Multi-tag Model Output"
    schema["description"] = (
        "Model-authored portion of the single-object design DNA result; "
        "derived_style_presets is added later by deterministic Python rules."
    )
    definitions = schema.get("$defs", {})
    definitions.pop("derivedStylePreset", None)
    style_result = definitions.get("styleResult", {})
    required = style_result.get("required", [])
    style_result["required"] = [
        item for item in required if item != "derived_style_presets"
    ]
    style_result.get("properties", {}).pop("derived_style_presets", None)
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        rendered = _render()
        if args.check:
            if args.output.read_text(encoding="utf-8") != rendered:
                print("model output schema is stale", file=sys.stderr)
                return 1
            print("model output schema is current")
            return 0
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

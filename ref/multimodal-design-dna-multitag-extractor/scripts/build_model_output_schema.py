#!/usr/bin/env python3
"""生成或检查由最终稳定定义派生的精简模型观察 Schema。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from build_observation_schema import build_schema


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "schemas" / "design-dna-model-output.schema.json"


def _render() -> str:
    return json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n"


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

#!/usr/bin/env python3
"""Build a system/context prompt bundle for agents without native Skill support."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write bundle to this file; otherwise print to stdout")
    args = parser.parse_args()

    protocol = (ROOT / "references" / "extraction-protocol.zh-CN.md").read_text(encoding="utf-8")
    category = (ROOT / "references" / "category-adaptation.zh-CN.md").read_text(encoding="utf-8")
    novelty = (ROOT / "references" / "novel-dna-governance.zh-CN.md").read_text(encoding="utf-8")
    kb = (ROOT / "references" / "design-dna-knowledge-base.zh-CN.md").read_text(encoding="utf-8")
    model_references = (ROOT / "references" / "model-reference-bundle.json").read_text(encoding="utf-8")
    schema = (ROOT / "schemas" / "design-dna-model-output.schema.json").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    schema_version = manifest["model_output_schema_version"]

    bundle = f"""# SYSTEM CONTEXT: Multimodal Design DNA Multi-Tag Extractor\n\n{protocol}\n\n<CATEGORY_ADAPTATION>\n{category}\n</CATEGORY_ADAPTATION>\n\n<NOVEL_DNA_GOVERNANCE>\n{novelty}\n</NOVEL_DNA_GOVERNANCE>\n\n<MODEL_REFERENCE_BUNDLE>\n{model_references}\n</MODEL_REFERENCE_BUNDLE>\n\n<DESIGN_DNA_KNOWLEDGE_BASE mode=\"full\">\n{kb}\n</DESIGN_DNA_KNOWLEDGE_BASE>\n\n<AUTHORITATIVE_MODEL_JSON_SCHEMA>\n{schema}\n</AUTHORITATIVE_MODEL_JSON_SCHEMA>\n\n最终只输出符合 {schema_version} 的精简观察 JSON；静态元数据、统计、排序、候选镜像、证据闭环和组合预设由宿主编译。图片必须作为单独的视觉输入随请求传入。\n"""
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(bundle, encoding="utf-8")
        print(f"wrote {args.output} ({len(bundle):,} chars)")
    else:
        print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

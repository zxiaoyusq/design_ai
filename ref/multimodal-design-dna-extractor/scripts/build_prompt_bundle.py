#!/usr/bin/env python3
"""Build a system/context prompt bundle for agents without native Skill support."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write bundle to this file; otherwise print to stdout")
    parser.add_argument("--knowledge-mode", choices=["full", "index"], default="full")
    args = parser.parse_args()

    protocol = (ROOT / "references" / "extraction-protocol.zh-CN.md").read_text(encoding="utf-8")
    contract = (ROOT / "references" / "output-contract.zh-CN.md").read_text(encoding="utf-8")
    category = (ROOT / "references" / "category-adaptation.zh-CN.md").read_text(encoding="utf-8")
    novelty = (ROOT / "references" / "novel-dna-governance.zh-CN.md").read_text(encoding="utf-8")
    kb_name = "design-dna-knowledge-base.zh-CN.md" if args.knowledge_mode == "full" else "knowledge-index.zh-CN.md"
    kb = (ROOT / "references" / kb_name).read_text(encoding="utf-8")

    bundle = f"""# SYSTEM CONTEXT: Multimodal Design DNA Extractor\n\n{protocol}\n\n<OUTPUT_CONTRACT>\n{contract}\n</OUTPUT_CONTRACT>\n\n<CATEGORY_ADAPTATION>\n{category}\n</CATEGORY_ADAPTATION>\n\n<NOVEL_DNA_GOVERNANCE>\n{novelty}\n</NOVEL_DNA_GOVERNANCE>\n\n<DESIGN_DNA_KNOWLEDGE_BASE mode=\"{args.knowledge_mode}\">\n{kb}\n</DESIGN_DNA_KNOWLEDGE_BASE>\n\n最终只输出符合 design_dna_extraction_v3.1 的 JSON。图片必须作为单独的视觉输入随请求传入。\n"""
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(bundle, encoding="utf-8")
        print(f"wrote {args.output} ({len(bundle):,} chars)")
    else:
        print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

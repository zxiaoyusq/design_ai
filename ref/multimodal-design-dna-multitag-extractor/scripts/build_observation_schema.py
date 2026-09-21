#!/usr/bin/env python3
"""由最终 Schema 的稳定视觉定义生成精简模型观察 Schema。"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL_SCHEMA = ROOT / "schemas" / "design-dna-output.schema.json"
OUTPUT_SCHEMA = ROOT / "schemas" / "design-dna-model-output.schema.json"


def build_schema() -> dict:
    final_schema = json.loads(FINAL_SCHEMA.read_text(encoding="utf-8"))
    final_defs = final_schema["$defs"]
    # 模型可见 Schema 的定义名也统一为 snake_case，避免被误当成输出字段名。
    reused_defs = {
        "target_object": final_defs["targetObject"],
        "image_quality": final_defs["imageQuality"],
        "evidence": final_defs["evidence"],
        "novel_dna": final_defs["novelDna"],
        "rule_adaptation": final_defs["ruleAdaptation"],
    }
    reused_defs.update(
        {
            "design_observation": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "field_id",
                    "value",
                    "raw_visual_description",
                    "region",
                    "observability",
                    "confidence",
                    "evidence_refs",
                ],
                "properties": {
                    "field_id": {
                        "type": "string",
                        "pattern": "^[A-Z][A-Z0-9_]*-[0-9]{2,3}$",
                    },
                    "value": {},
                    "raw_visual_description": {"type": "string"},
                    "region": {"type": "string", "minLength": 1},
                    "observability": {
                        "enum": ["observed", "not_observable", "unknown"]
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_refs": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "pattern": "^EV-[A-Za-z0-9_-]+$",
                        },
                        "uniqueItems": True,
                    },
                },
            },
            "style_candidate_observation": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "style_id",
                    "match_score",
                    "confidence",
                    "regions",
                    "main_support",
                    "main_conflicts",
                ],
                "properties": {
                    "style_id": final_defs["styleId"],
                    "match_score": {"type": "number", "minimum": 0, "maximum": 100},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "regions": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                    "main_support": {
                        "description": "图片中直接支持该候选的主要视觉依据。",
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                    "main_conflicts": {
                        "description": "可见但削弱该候选的主要冲突；没有时返回空数组。",
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "uniqueItems": True,
                    },
                },
            },
            "style_observations": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_tags",
                    "composition_summary",
                ],
                "properties": {
                    "candidate_tags": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/style_candidate_observation"},
                        "maxItems": 5,
                    },
                    "composition_summary": {"type": "string", "minLength": 1},
                },
            },
            "quality_notes": {
                "type": "object",
                "additionalProperties": False,
                "required": ["missing_critical_fields", "warnings", "concise_summary"],
                "properties": {
                    "missing_critical_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "uniqueItems": True,
                    },
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string"},
                        "uniqueItems": True,
                    },
                    "concise_summary": {"type": "string", "minLength": 1},
                },
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.internal/schemas/design-dna-multitag-observation-v3.json",
        "title": "Multimodal Design DNA Multi-tag Model Observation",
        "description": "Lean model-authored visual and semantic observations; the host compiles deterministic metadata, statistics, ordering, references, and final result fields.",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "knowledge_base_version",
            "target_object",
            "image_quality",
            "active_profiles",
            "rule_adaptations",
            "style_observations",
            "design_observations",
            "novel_dna_elements",
            "evidence",
            "quality_notes",
        ],
        "properties": {
            "schema_version": {"const": "design_dna_multitag_observation_v3"},
            "knowledge_base_version": {"const": "4.1"},
            "target_object": {"$ref": "#/$defs/target_object"},
            "image_quality": {
                "description": "顶层键名固定使用 snake_case 的 image_quality。",
                "$ref": "#/$defs/image_quality",
            },
            "active_profiles": {
                "type": "array",
                "items": {
                    "enum": [
                        "core",
                        "profile:device_controls",
                        "profile:imaging_device",
                        "profile:screen_device",
                        "profile:handled_object",
                        "profile:portable_object",
                        "profile:contact_surface",
                    ]
                },
                "minItems": 1,
                "uniqueItems": True,
                "contains": {"const": "core"},
            },
            "rule_adaptations": {
                "type": "array",
                "items": {"$ref": "#/$defs/rule_adaptation"},
            },
            "style_observations": {"$ref": "#/$defs/style_observations"},
            "design_observations": {
                "type": "array",
                "items": {"$ref": "#/$defs/design_observation"},
                "minItems": 1,
            },
            "novel_dna_elements": {
                "type": "array",
                "items": {"$ref": "#/$defs/novel_dna"},
            },
            "evidence": {
                "type": "array",
                "items": {"$ref": "#/$defs/evidence"},
                "minItems": 1,
            },
            "quality_notes": {
                "description": "顶层键名固定使用 snake_case 的 quality_notes。",
                "$ref": "#/$defs/quality_notes",
            },
        },
        "$defs": reused_defs,
    }


def main() -> int:
    schema = build_schema()
    OUTPUT_SCHEMA.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT_SCHEMA)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

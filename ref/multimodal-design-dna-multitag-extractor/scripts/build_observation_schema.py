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
    reused_defs = {
        name: final_defs[name]
        for name in (
            "targetObject",
            "imageQuality",
            "candidateValue",
            "evidence",
            "novelDna",
            "ruleAdaptation",
        )
    }
    reused_defs.update(
        {
            "designObservation": {
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
            "confirmedStyleObservation": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "style_id",
                    "match_score",
                    "confidence",
                    "dominance",
                    "regions",
                    "applicable_rule_count",
                    "not_applicable_rule_count",
                    "color_requirement_status",
                    "core_feature_hits",
                    "auxiliary_feature_hits",
                ],
                "properties": {
                    "style_id": final_defs["styleId"],
                    "match_score": {"type": "number", "minimum": 0, "maximum": 100},
                    "confidence": {"type": "number", "minimum": 0.75, "maximum": 1},
                    "dominance": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                    "regions": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                    "applicable_rule_count": {"type": "integer", "minimum": 1},
                    "not_applicable_rule_count": {"type": "integer", "minimum": 0},
                    "color_requirement_status": {"enum": ["pass", "not_applicable"]},
                    "core_feature_hits": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                    "auxiliary_feature_hits": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "uniqueItems": True,
                    },
                },
            },
            "otherStyleCandidate": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "style_id",
                    "match_score",
                    "confidence",
                    "regions",
                    "candidate_status",
                    "hard_rule_passed",
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
                        "uniqueItems": True,
                    },
                    "candidate_status": {"enum": ["provisional", "rejected"]},
                    "hard_rule_passed": {"type": "boolean"},
                    "main_support": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "uniqueItems": True,
                    },
                    "main_conflicts": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "uniqueItems": True,
                    },
                },
                "allOf": [
                    {
                        "if": {
                            "properties": {"hard_rule_passed": {"const": True}},
                            "required": ["hard_rule_passed"],
                        },
                        "then": {"properties": {"main_conflicts": {"minItems": 1}}},
                    }
                ],
            },
            "pairwiseReasoning": {
                "type": "object",
                "additionalProperties": False,
                "required": ["style_id_a", "style_id_b", "reason"],
                "properties": {
                    "style_id_a": final_defs["styleId"],
                    "style_id_b": final_defs["styleId"],
                    "reason": {"type": "string", "minLength": 1},
                },
            },
            "styleObservations": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "classification_status",
                    "confirmed_tags",
                    "other_candidates",
                    "pairwise_reasoning",
                    "composition_summary",
                ],
                "properties": {
                    "classification_status": {"enum": ["confirmed", "unclassified"]},
                    "confirmed_tags": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/confirmedStyleObservation"},
                        "maxItems": 3,
                    },
                    "other_candidates": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/otherStyleCandidate"},
                    },
                    "pairwise_reasoning": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/pairwiseReasoning"},
                        "maxItems": 3,
                    },
                    "composition_summary": {"type": "string", "minLength": 1},
                },
                "allOf": [
                    {
                        "if": {
                            "properties": {"classification_status": {"const": "confirmed"}},
                            "required": ["classification_status"],
                        },
                        "then": {"properties": {"confirmed_tags": {"minItems": 1}}},
                    },
                    {
                        "if": {
                            "properties": {"classification_status": {"const": "unclassified"}},
                            "required": ["classification_status"],
                        },
                        "then": {
                            "properties": {
                                "confirmed_tags": {"maxItems": 0},
                                "other_candidates": {"minItems": 1},
                                "pairwise_reasoning": {"maxItems": 0},
                            }
                        },
                    },
                    {
                        "if": {
                            "properties": {"confirmed_tags": {"minItems": 2, "maxItems": 2}},
                            "required": ["confirmed_tags"],
                        },
                        "then": {"properties": {"pairwise_reasoning": {"minItems": 1, "maxItems": 1}}},
                    },
                    {
                        "if": {
                            "properties": {"confirmed_tags": {"minItems": 3, "maxItems": 3}},
                            "required": ["confirmed_tags"],
                        },
                        "then": {"properties": {"pairwise_reasoning": {"minItems": 3, "maxItems": 3}}},
                    },
                ],
            },
            "uncertaintyObservation": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "field_id",
                    "region",
                    "reason_type",
                    "reason",
                    "observability",
                    "confidence",
                    "evidence_refs",
                    "best_estimate",
                    "candidate_values",
                    "recommended_additional_view_or_info",
                ],
                "properties": {
                    "field_id": {
                        "type": "string",
                        "pattern": "^[A-Z][A-Z0-9_]*-[0-9]{2,3}$",
                    },
                    "region": {"type": "string", "minLength": 1},
                    "reason_type": final_defs["uncertainField"]["properties"]["reason_type"],
                    "reason": {"type": "string", "minLength": 1},
                    "observability": {
                        "enum": ["observed", "not_observable", "unknown"]
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 0.749999},
                    "evidence_refs": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "pattern": "^EV-[A-Za-z0-9_-]+$",
                        },
                        "uniqueItems": True,
                    },
                    "best_estimate": {},
                    "candidate_values": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/candidateValue"},
                        "maxItems": 3,
                    },
                    "recommended_additional_view_or_info": {"type": "string"},
                },
            },
            "qualityNotes": {
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
        "$id": "https://example.internal/schemas/design-dna-multitag-observation-v1.json",
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
            "uncertainties",
            "novel_dna_elements",
            "evidence",
            "quality_notes",
        ],
        "properties": {
            "schema_version": {"const": "design_dna_multitag_observation_v1"},
            "knowledge_base_version": {"const": "4.1"},
            "target_object": {"$ref": "#/$defs/targetObject"},
            "image_quality": {"$ref": "#/$defs/imageQuality"},
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
                "items": {"$ref": "#/$defs/ruleAdaptation"},
            },
            "style_observations": {"$ref": "#/$defs/styleObservations"},
            "design_observations": {
                "type": "array",
                "items": {"$ref": "#/$defs/designObservation"},
                "minItems": 1,
            },
            "uncertainties": {
                "type": "array",
                "items": {"$ref": "#/$defs/uncertaintyObservation"},
            },
            "novel_dna_elements": {
                "type": "array",
                "items": {"$ref": "#/$defs/novelDna"},
            },
            "evidence": {
                "type": "array",
                "items": {"$ref": "#/$defs/evidence"},
                "minItems": 1,
            },
            "quality_notes": {"$ref": "#/$defs/qualityNotes"},
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

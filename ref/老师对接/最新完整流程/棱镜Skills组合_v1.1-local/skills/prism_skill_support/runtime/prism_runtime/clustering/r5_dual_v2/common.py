"""Finite, typed JSON identity and source references; no execution transport."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

VERSION = "r5-dual-clustering-v2.0.0"
BASELINE = "sol-coverage-dna-r5-20260929"


def need(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + x)))


def identity(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def checked_file(ref):
    need(identity(ref["path"]) == ref, "File identity changed: " + ref["path"])
    return read(ref["path"])


def seal(value):
    result = deepcopy(value)
    result["digest"] = digest(result)
    return result


def verify(value):
    need(value.get("digest") == digest({k: v for k, v in value.items() if k != "digest"}), "Bound JSON changed")


def indexed(rows, key):
    need(isinstance(rows, list), "Expected an explicit list: " + key)
    result = {r[key]: r for r in rows}
    need(len(result) == len(rows) and all(isinstance(x, str) and x for x in result), "Duplicate/invalid " + key)
    return result

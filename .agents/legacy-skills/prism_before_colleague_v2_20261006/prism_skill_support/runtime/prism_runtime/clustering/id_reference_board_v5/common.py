"""Local finite JSON and immutable evidence. No execution or image processing."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

VERSION = "id-reference-board-v5.0.0"


def need(ok, message):
    if not ok:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode("utf-8")).hexdigest()


def read(path):
    def pairs(items):
        out = {}
        for k, v in items:
            need(k not in out, "duplicate_json_key:" + k)
            out[k] = v
        return out
    def bad(value):
        raise ValueError("nonfinite_json:" + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=bad)


def identity(path):
    name = str(path)
    need("://" not in name and not name.startswith(("\\\\", "//")), "local_file_required")
    p = Path(name)
    need(p.is_absolute() and p.is_file(), "absolute_existing_file_required:" + name)
    return {"path": str(p.resolve()), "sha256": digest(p.read_bytes())}


def checked(ref, parse=True):
    need(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "FileRef_required")
    actual = identity(ref["path"])
    need(actual["sha256"] == ref["sha256"], "file_hash_changed:" + ref["path"])
    return read(ref["path"]) if parse else actual


def pointer(value, path):
    need(isinstance(path, str) and (path == "" or path.startswith("/")), "json_pointer_required")
    for part in path[1:].split("/") if path else []:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def pick(evidence):
    return pointer(checked(evidence["ref"]), evidence["pointer"])


def indexed(rows, key):
    need(isinstance(rows, list), "list_required:" + key)
    need(all(isinstance(r, dict) and text(r.get(key)) for r in rows), "row_key_required:" + key)
    result = {r[key]: r for r in rows}
    need(len(result) == len(rows), "duplicate:" + key)
    return result


def seal(value):
    out = deepcopy(value)
    out["digest"] = digest(out)
    return out


def verify(value):
    need(value.get("digest") == digest({k: v for k, v in value.items() if k != "digest"}), "sealed_value_changed")


def reject_fixture(value, mode):
    if mode != "real":
        return
    if isinstance(value, dict):
        need(value.get("fixture_only") is not True and value.get("not_a_model_output") is not True
             and value.get("dataset_mode") != "synthetic_fixture"
             and value.get("actor_kind") != "synthetic_fixture", "synthetic_evidence_in_real_mode")
        for child in value.values():
            reject_fixture(child, mode)
    elif isinstance(value, list):
        for child in value:
            reject_fixture(child, mode)


def pins():
    refs = read(Path(__file__).with_name("dependencies.json"))
    for ref in refs.values():
        ref["path"] = str((Path(__file__).parent / ref["path"]).resolve())
        checked(ref, False)
    return refs


def review_provenance(row, required_refs, mode):
    """Require an external review record, not default-true template booleans.

    This checks traceability; only the reviewing person/model can judge pixels.
    """
    reject_fixture(row, mode)
    provenance = row.get("review_provenance")
    need(isinstance(provenance, dict) and provenance.get("actor_kind") in
         {"human", "model", "synthetic_fixture"} and text(provenance.get("actor_id")), "review_provenance_required")
    source = checked(provenance["source_ref"])
    reject_fixture(source, mode)
    inspected = provenance.get("inspected_refs", [])
    for ref in inspected:
        checked(ref, False)
    need(all(ref in inspected for ref in required_refs), "actual_review_inputs_missing")
    need(text(provenance.get("basis")), "review_provenance_basis_required")
    return deepcopy(provenance)

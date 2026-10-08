"""Small source/contract helpers; no model, visual, or network execution."""
from copy import deepcopy
from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
VERSION = "handshake-semantic-h01-skill-v1.0.0"
WORKFLOW = ROOT / "workflow_h01.py"



class ContractError(ValueError):
    pass


def need(ok, message):
    if not ok: raise ContractError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def identity(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read(path):
    def pairs(items):
        row = {}
        for key, value in items:
            need(key not in row, "Duplicate JSON key: " + key)
            row[key] = value
        return row
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda s: (_ for _ in ()).throw(ContractError("Nonfinite JSON value")))


def write(path, value):
    path = Path(path)
    need(not path.exists(), "Use a new artifact path: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def seal(value):
    value = deepcopy(value)
    need("digest" not in value, "Do not silently reseal an existing artifact")
    value["digest"] = digest(value)
    return value


def verify(value):
    need(isinstance(value, dict) and value.get("digest") == digest({k: v for k, v in value.items() if k != "digest"}), "Artifact was modified after binding")
    return value


def index(rows, field):
    need(isinstance(rows, list), field + " rows must be an array")
    result = {}
    for row in rows:
        key = row.get(field)
        need(isinstance(key, str) and key and key not in result, "Missing/duplicate " + field)
        result[key] = row
    return result


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workflow():
    module = load_module(WORKFLOW, "handshake_bound_workflow_v2")
    need(module.VERSION == "prism.semantic-first-dual-h02.v2", "Unsupported Root workflow contract")
    return module


def research_compiler(folder=None):
    """Execute the existing pure compiler with its own prepare namespace.

    Its bare `from prepare import ...` is resolved locally, without changing
    shared sys.modules/sys.path or editing the upstream module.
    """
    folder = Path(folder) if folder else ROOT / "research_core"
    prep = load_module(folder / "prepare.py", "handshake_research_source_prepare")
    tree = ast.parse((folder / "compile.py").read_text(encoding="utf-8-sig"))
    nodes = []
    ns = {"__name__": "handshake_research_source_compiler", "__file__": str(folder / "compile.py")}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "prepare":
            for name in node.names: ns[name.asname or name.name] = getattr(prep, name.name)
        else: nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(folder / "compile.py"), "exec"), ns)
    return ns, [identity(folder / "prepare.py"), identity(folder / "compile.py")]


def validate_schema(value, schema):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ContractError("Install this skill's requirements.txt in your Python environment before H01 validation") from exc
    errors = list(Draft202012Validator(schema).iter_errors(value))
    need(not errors, "Response schema mismatch: " + (errors[0].message if errors else ""))


def object_schema(fields):
    return {"type": "object", "additionalProperties": False, "required": list(fields), "properties": fields}


def check_provider_schema(schema):
    """Additional transport guards beyond Draft202012 syntax validity."""
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("const"), str):
                need(value.get("type") == "string", "Provider string const must explicitly declare type:string")
            if "enum" in value:
                need(bool(value["enum"]), "Provider schema cannot use an empty enum")
                need("type" in value, "Provider enum must have an explicit type")
            need("uniqueItems" not in value, "Provider schema must not contain uniqueItems; retain it in the local normative validator")
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(schema)
    return schema


def wire_schema(normative):
    """Transport-only projection. Local acceptance still uses the full schema."""
    changes = []
    def walk(value, path="$"):
        if isinstance(value, list): return [walk(v, path + "/" + str(i)) for i, v in enumerate(value)]
        if not isinstance(value, dict): return deepcopy(value)
        out = {}
        for key, child in value.items():
            if key == "uniqueItems":
                changes.append({"path": path + "/uniqueItems", "operation": "omit_from_wire_only", "normative_value": child})
            else: out[key] = walk(child, path + "/" + key)
        if "type" not in out and ("const" in out or "enum" in out):
            vals = out.get("enum", [out.get("const")])
            need(vals, "Empty enum is not a usable model contract")
            def kind(v):
                if v is None: return "null"
                if isinstance(v, bool): return "boolean"
                if isinstance(v, str): return "string"
                if isinstance(v, int): return "integer"
                if isinstance(v, float): return "number"
                if isinstance(v, list): return "array"
                if isinstance(v, dict): return "object"
                raise ContractError("Unsupported enum value")
            kinds = sorted({kind(v) for v in vals})
            out["type"] = kinds[0] if len(kinds) == 1 else kinds
            changes.append({"path": path + "/type", "operation": "declare_implied_type", "value": out["type"]})
        return out
    result = check_provider_schema(walk(normative))
    return result, {"changes": changes, "normative_schema_digest": digest(normative),
                    "wire_schema_digest": digest(result), "local_full_schema_validation_required": True,
                    "model_reply_auto_deduplication_allowed": False}


STRING = {"type": "string", "minLength": 1}


def ids_schema(values, minimum=0, exact=False):
    value = {"type": "array", "items": {"type": "string"}, "uniqueItems": True, "minItems": minimum}
    if values: value["items"]["enum"] = list(values)
    else: value["maxItems"] = 0
    if exact: value.update(minItems=len(values), maxItems=len(values))
    return value

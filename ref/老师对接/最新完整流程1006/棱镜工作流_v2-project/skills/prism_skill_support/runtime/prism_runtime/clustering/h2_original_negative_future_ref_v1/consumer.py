"""An opt-in private consumer with one frozen future-reference guard replaced."""
import ast
from copy import deepcopy
import importlib
import importlib.util
import inspect
from pathlib import Path
import sys
import threading
import types

from ..id_reference_board_v5.common import checked, digest, need, read, seal
from ..r5_exact_byte_alias_v1 import consumer as original_consumer, load_record
from ..r5_exact_byte_alias_v1.registry import dependencies as original_dependencies
from ..r5_dual_v2.adapter import producer
from .references import SCHEMA, VERSION, future_gate, validate_future_references

_CACHE = {}
_LOCK = threading.RLock()


def dependencies():
    own = read(Path(__file__).with_name("dependencies.json"))
    for ref in own["alias_adapter_pins"] + [own["base_consumer_registry_ref"]]:
        ref["path"] = str((Path(__file__).parent / ref["path"]).resolve())
    for ref in own["alias_adapter_pins"]:
        checked(ref, False)
    checked(own["base_consumer_registry_ref"])
    return own, original_dependencies()


def _package(name):
    m = types.ModuleType(name)
    m.__package__ = name
    m.__path__ = []
    sys.modules[name] = m


def consumer(branch, *, future_reference_ref=None):
    """Default preserves the old guard; opt-in binds one immutable sidecar.

    Use this API for grouping and every later replay. No original consumer,
    alias consumer, global function, source file or audit array is modified.
    """
    _, registry = dependencies()
    need(branch in {"CMF", "ID"}, "CMF_or_ID_consumer_required")
    if future_reference_ref is None:
        return original_consumer(branch)
    ref = deepcopy(future_reference_ref)
    document = checked(ref)
    need(document.get("schema_version") == SCHEMA and document.get("branch") == branch, "future_reference_branch_schema_mismatch")
    key = digest([branch, ref])
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
        root = __package__ + "._private_" + key[:24]
        _package(root)
        _package(root + ".r5_dual_v2")
        bridge = types.ModuleType(root + ".r5_dual_v2.adapter")
        bridge.load_record, bridge.producer = load_record, producer
        sys.modules[bridge.__name__] = bridge
        entry = registry["consumers"][branch]
        name = root + "." + entry["package_name"]
        spec = importlib.util.spec_from_file_location(name, entry["init_ref"]["path"],
                    submodule_search_locations=[str(Path(entry["init_ref"]["path"]).parent)])
        api = importlib.util.module_from_spec(spec)
        sys.modules[name] = api
        spec.loader.exec_module(api)
        protocol = importlib.import_module(name + ".protocol")
        tree = ast.parse(inspect.getsource(protocol.accept_grouping))
        replacements = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "need"
                    and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "future_negative_must_retain_original_obligation"):
                node.func = ast.Name(id="_original_negative_future_gate", ctx=ast.Load())
                node.args = [ast.Name(id=n, ctx=ast.Load()) for n in ("prepared", "proposal_ref", "row")]
                replacements += 1
        need(replacements == 1, "expected_one_frozen_future_guard")
        protocol._original_negative_future_gate = lambda p, proposal, row: future_gate(p, proposal, row, ref)
        exec(compile(ast.fix_missing_locations(tree), protocol.__file__, "exec"), protocol.__dict__)
        patched = protocol.accept_grouping

        def accept_grouping(prepared, proposal_ref):
            dependencies()
            supplemental = validate_future_references(prepared, proposal_ref, ref)
            result = patched(prepared, proposal_ref)
            # This separate, sealed audit edge never changes either frozen array
            # or the model's original disposition/proposal.
            result.pop("digest")
            result["original_negative_future_reference"] = {
                "adapter_version": VERSION, "reference_ref": deepcopy(ref), "document": supplemental,
            }
            return seal(result)

        protocol.accept_grouping = accept_grouping
        api.accept_grouping = accept_grouping
        _CACHE[key] = api
        return api

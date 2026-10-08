"""Unmodified frozen consumer sources in an isolated relative-import namespace."""
import importlib.util
from pathlib import Path
import sys
import threading
import types

from ..id_reference_board_v5.common import need
from ..r5_dual_v2.adapter import producer
from .adapter import load_record
from .registry import dependencies

_ROOT = __package__ + "._private"
_CACHE = {}
_LOCK = threading.RLock()


def _package(name):
    module = types.ModuleType(name)
    module.__path__ = []
    module.__package__ = name
    sys.modules[name] = module
    return module


def consumer(branch):
    """Return frozen CMF v4 or ID v5 API; only its private R5 import is routed.

    No original sys.modules entry, source file or global function is replaced.
    Keep using this returned API for every stage so current() uses the same
    exact-byte validator when it replays an aliased record.
    """
    need(branch in {"CMF", "ID"}, "CMF_or_ID_consumer_required")
    manifest = dependencies()
    with _LOCK:
        if branch in _CACHE:
            return _CACHE[branch]
        if _ROOT not in sys.modules:
            _package(_ROOT)
            _package(_ROOT + ".r5_dual_v2")
            bridge = types.ModuleType(_ROOT + ".r5_dual_v2.adapter")
            bridge.__package__ = _ROOT + ".r5_dual_v2"
            bridge.load_record = load_record
            bridge.producer = producer
            sys.modules[bridge.__name__] = bridge
        entry = manifest["consumers"][branch]
        name = _ROOT + "." + entry["package_name"]
        spec = importlib.util.spec_from_file_location(name, entry["init_ref"]["path"],
                                                     submodule_search_locations=[str(Path(entry["init_ref"]["path"]).parent)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            # Remove only this wrapper's incomplete private consumer namespace.
            for key in list(sys.modules):
                if key == name or key.startswith(name + "."):
                    sys.modules.pop(key, None)
            raise
        _CACHE[branch] = module
        return module

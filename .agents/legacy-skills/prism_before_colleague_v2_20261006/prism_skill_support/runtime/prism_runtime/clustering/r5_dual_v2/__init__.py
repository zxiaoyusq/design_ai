"""Offline R5 dual-route candidate grouping; no model or image-editing runner."""
from .adapter import adapt_r5, load_record
from .common import VERSION, digest
from .engine import cluster, validate_request
from .scope import prepare_scope

__all__ = ["VERSION", "prepare_scope", "adapt_r5", "load_record", "validate_request", "cluster", "digest"]

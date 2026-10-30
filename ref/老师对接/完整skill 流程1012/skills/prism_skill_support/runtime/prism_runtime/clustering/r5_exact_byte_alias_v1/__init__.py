"""Exact-byte task-ID compatibility; no new DNA/quality execution."""
from .adapter import VERSION, load_record
from .consumers import consumer

__all__ = ["VERSION", "load_record", "consumer"]

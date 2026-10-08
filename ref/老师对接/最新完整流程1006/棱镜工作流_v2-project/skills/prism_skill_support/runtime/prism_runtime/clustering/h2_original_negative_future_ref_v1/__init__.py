"""Opt-in exact original-negative links for already-deferred future checks."""
from .references import VERSION, derive_future_references, validate_future_references
from .consumer import consumer

__all__ = ["VERSION", "derive_future_references", "validate_future_references", "consumer"]

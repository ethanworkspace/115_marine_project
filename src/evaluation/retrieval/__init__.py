"""Retrieval evaluation primitives; deliberately unbound to production retrievers."""

from .gold_resolver import GoldResolutionError, resolve_gold
from .metrics import metric_bundle, required_evidence_coverage

__all__ = ["GoldResolutionError", "resolve_gold", "metric_bundle", "required_evidence_coverage"]

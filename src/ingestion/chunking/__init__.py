"""Experimental, provenance-preserving Chunking v2 shadow pipeline."""

from .models import ChunkRecord


def build_shadow_corpus(*args, **kwargs):
    """Load the runner lazily so chunker unit tests need no PDF/OCR dependencies."""
    from .pipeline import build_shadow_corpus as _build_shadow_corpus
    return _build_shadow_corpus(*args, **kwargs)


__all__ = ["ChunkRecord", "build_shadow_corpus"]

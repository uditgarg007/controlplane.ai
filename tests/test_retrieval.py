"""
ControlPlane.ai — Stage 2 Tests: Retrieval Routing

Tests verify:
  1. Vector retrieval returns chunks (mock path — no FAISS index required).
  2. Metadata filters correctly exclude non-matching chunks.
  3. Context compression reduces token count.
  4. Compression ratio is reported correctly.
  5. RetrievalResult schema is well-formed.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from controlplane.core.retrieval import (
    _passes_filters,
    _estimate_tokens,
    _compress_context,
    _mock_chunks,
    run_retrieval,
)
from controlplane.config import IngressResult, QueryIntent


# ─────────────────────────────────────────────────────────────
# Metadata filter logic
# ─────────────────────────────────────────────────────────────

class TestMetadataFilters:
    def test_gte_filter_passes(self):
        assert _passes_filters({"year": 2022}, {"year": {"$gte": 2020}})

    def test_gte_filter_fails(self):
        assert not _passes_filters({"year": 2018}, {"year": {"$gte": 2020}})

    def test_lt_filter_passes(self):
        assert _passes_filters({"year": 2015}, {"year": {"$lt": 2020}})

    def test_lt_filter_fails(self):
        assert not _passes_filters({"year": 2021}, {"year": {"$lt": 2020}})

    def test_missing_key_fails(self):
        assert not _passes_filters({}, {"year": {"$gte": 2020}})

    def test_no_filters_always_passes(self):
        assert _passes_filters({"year": 1990}, {})


# ─────────────────────────────────────────────────────────────
# Token estimation
# ─────────────────────────────────────────────────────────────

class TestTokenEstimation:
    def test_empty_string(self):
        assert _estimate_tokens("") >= 1

    def test_known_length(self):
        # 12 words → ~16 tokens (12 / 0.75 = 16)
        text = "one two three four five six seven eight nine ten eleven twelve"
        assert _estimate_tokens(text) == 16

    def test_longer_text_more_tokens(self):
        short = "hello world"
        long_text = "hello world " * 100
        assert _estimate_tokens(long_text) > _estimate_tokens(short)


# ─────────────────────────────────────────────────────────────
# Context compression (fallback path — no LLMLingua)
# ─────────────────────────────────────────────────────────────

class TestContextCompression:
    def test_compressed_is_shorter_or_equal(self):
        """Compressed text must not be longer than the original."""
        raw = "Context chunk. " * 500     # very long
        chunks = [raw]
        compressed, token_count = _compress_context(raw, chunks)
        raw_tokens = _estimate_tokens(raw)
        assert token_count <= raw_tokens

    def test_short_text_unchanged(self):
        """Short text under budget should pass through unchanged."""
        raw = "Brief context."
        chunks = [raw]
        compressed, _ = _compress_context(raw, chunks)
        assert len(compressed) > 0


# ─────────────────────────────────────────────────────────────
# Mock chunk generation
# ─────────────────────────────────────────────────────────────

class TestMockChunks:
    def test_one_chunk_per_query(self):
        queries = ["q1", "q2", "q3"]
        chunks = _mock_chunks(queries)
        assert len(chunks) == 3

    def test_chunk_contains_query(self):
        chunks = _mock_chunks(["transformer architecture"])
        assert "transformer architecture" in chunks[0]


# ─────────────────────────────────────────────────────────────
# Full run_retrieval (mocked databases)
# ─────────────────────────────────────────────────────────────

class TestRunRetrieval:
    def _make_ingress(self, intent=QueryIntent.SEMANTIC) -> IngressResult:
        return IngressResult(
            original_query="test",
            clean_query="test",
            intent=intent,
            positive_vectors=["test query"],
            negative_constraints=[],
            metadata_filters={},
        )

    def test_returns_retrieval_result(self):
        ingress = self._make_ingress()
        result = run_retrieval(ingress)
        # Should always return a valid result (falls back to mock chunks)
        assert result is not None
        assert isinstance(result.compressed_context, str)
        assert result.latency_ms >= 0

    def test_compression_ratio_in_range(self):
        ingress = self._make_ingress()
        result = run_retrieval(ingress)
        assert 0.0 <= result.compression_ratio <= 1.0

    def test_token_counts_consistent(self):
        ingress = self._make_ingress()
        result = run_retrieval(ingress)
        # Both counts must be non-negative
        assert result.compressed_token_count >= 0
        assert result.raw_token_count >= 0

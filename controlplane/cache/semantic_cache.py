"""
ControlPlane.ai — Semantic Cache

Runs PARALLEL to the main pipeline.  On every incoming query:
  1. Generate a query embedding.
  2. Check Redis for an exact-key hit (fast path).
  3. If miss, scan the in-process vector cache for a near-duplicate (cosine sim).
  4. On cache hit → return the cached answer instantly.
  5. On cache miss → pipeline runs normally; result is stored before returning.

This eliminates duplicate compute for repeated or paraphrased queries.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

import numpy as np
from loguru import logger

from controlplane.config import Config

# ─────────────────────────────────────────────────────────────
# Optional dependencies
# ─────────────────────────────────────────────────────────────
try:
    import redis as redis_lib

    _redis_client = redis_lib.from_url(Config.REDIS_URL, decode_responses=True)
    _redis_client.ping()
    _redis_available = True
    logger.info("Redis cache connected.")
except Exception as exc:
    logger.warning(f"Redis unavailable ({exc}) — using in-process cache only.")
    _redis_available = False

try:
    from sentence_transformers import SentenceTransformer

    _embed_model = SentenceTransformer(Config.EMBEDDING_MODEL)
    _embeddings_available = True
except ImportError:
    _embeddings_available = False

# ─────────────────────────────────────────────────────────────
# In-process vector cache (for near-duplicate detection)
# ─────────────────────────────────────────────────────────────
# Each entry: {"embedding": np.ndarray, "answer": str, "meta": dict}
_vector_cache: list[dict[str, Any]] = []

# Cosine similarity threshold for a "semantic hit"
_SEMANTIC_HIT_THRESHOLD = 0.92


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def cache_lookup(query: str) -> Optional[str]:
    """
    Try to serve the query from cache.

    Returns the cached answer string if found, else None.
    """
    # 1. Exact hash lookup via Redis
    key = _hash_key(query)
    if _redis_available:
        cached = _redis_client.get(key)
        if cached:
            logger.info(f"[Cache] Exact Redis hit for key {key[:8]}…")
            return cached

    # 2. Semantic / fuzzy lookup via in-process vector cache
    if _embeddings_available and _vector_cache:
        embedding = _embed(query)
        hit = _find_semantic_hit(embedding)
        if hit:
            logger.info("[Cache] Semantic hit — serving without re-computation.")
            return hit

    return None


def cache_store(query: str, answer: str, meta: dict | None = None) -> None:
    """
    Store a query→answer pair in both Redis (exact) and the vector cache (semantic).
    """
    key = _hash_key(query)

    # Exact cache via Redis
    if _redis_available:
        _redis_client.setex(key, Config.CACHE_TTL_SECONDS, answer)

    # Semantic cache in-process
    if _embeddings_available:
        embedding = _embed(query)
        _vector_cache.append({
            "embedding": embedding,
            "answer": answer,
            "meta": meta or {},
            "stored_at": time.time(),
        })
        _evict_stale_entries()


def cache_stats() -> dict[str, Any]:
    """Return current cache statistics for the metrics dashboard."""
    redis_keys = 0
    if _redis_available:
        try:
            redis_keys = _redis_client.dbsize()
        except Exception:
            pass
    return {
        "redis_entries": redis_keys,
        "vector_cache_entries": len(_vector_cache),
        "redis_available": _redis_available,
        "semantic_threshold": _SEMANTIC_HIT_THRESHOLD,
    }


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _hash_key(query: str) -> str:
    """Deterministic exact-match key: strip + lowercase + SHA-256."""
    normalised = query.strip().lower()
    return "cp:cache:" + hashlib.sha256(normalised.encode()).hexdigest()


def _embed(text: str) -> np.ndarray:
    vec = _embed_model.encode([text], normalize_embeddings=True)
    return vec[0].astype("float32")


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for L2-normalised vectors simplifies to dot product."""
    return float(np.dot(a, b))


def _find_semantic_hit(embedding: np.ndarray) -> Optional[str]:
    """Scan vector cache for the most similar entry above the threshold."""
    best_score = 0.0
    best_answer: Optional[str] = None

    for entry in _vector_cache:
        score = _cosine_similarity(embedding, entry["embedding"])
        if score > best_score:
            best_score = score
            best_answer = entry["answer"]

    if best_score >= _SEMANTIC_HIT_THRESHOLD:
        return best_answer
    return None


def _evict_stale_entries() -> None:
    """Remove entries older than CACHE_TTL_SECONDS from the in-process cache."""
    cutoff = time.time() - Config.CACHE_TTL_SECONDS
    before = len(_vector_cache)
    _vector_cache[:] = [e for e in _vector_cache if e.get("stored_at", 0) > cutoff]
    evicted = before - len(_vector_cache)
    if evicted:
        logger.debug(f"[Cache] Evicted {evicted} stale entries.")

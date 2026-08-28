"""
ControlPlane.ai — Shared Configuration & Data Models
All pipeline stages import from this single source of truth.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class QueryIntent(str, Enum):
    SEMANTIC = "semantic"          # simple vector lookup
    MULTI_HOP = "multi_hop"       # graph traversal needed
    CONVERSATIONAL = "conversational"
    MALICIOUS = "malicious"       # blocked at ingress


class SeverityLevel(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    QUARANTINE = "quarantine"
    REDACT = "redact"


class UserRole(str, Enum):
    ADMIN = "admin"
    INTERNAL = "internal"
    EXTERNAL = "external"


class UserContext(BaseModel):
    user_id: str = "anonymous"
    role: UserRole = UserRole.EXTERNAL
    geography: str = "US"


class PolicyProfile(BaseModel):
    name: str
    align_score_threshold: float
    guard_block_composite_threshold: float
    guard_block_signal_threshold: float
    pii_masking_enabled: bool = True
    quarantine_on_warn: bool = False



class RepairChannel(str, Enum):
    VECTOR = "vector"
    GRAPH = "graph"
    WEB = "web"


# ─────────────────────────────────────────────
# Pipeline Data Models
# ─────────────────────────────────────────────

class IngressResult(BaseModel):
    """Output of Stage 1 — Ingress & Decomposer."""
    original_query: str
    clean_query: str
    intent: QueryIntent
    positive_vectors: list[str] = Field(default_factory=list)   # what to find
    negative_constraints: list[str] = Field(default_factory=list)  # what to exclude
    pii_detected: bool = False
    pii_entities: list[dict[str, Any]] = Field(default_factory=list)
    metadata_filters: dict[str, Any] = Field(default_factory=dict)
    blocked: bool = False
    block_reason: Optional[str] = None
    # InputGuard fields — pre-LLM security gate results
    guard_risk_score: float = 0.0
    guard_verdict: str = "allow"      # "allow" | "warn" | "block"
    guard_signals: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = 0.0


class RetrievalResult(BaseModel):
    """Output of Stage 2 — Retrieval Routing."""
    raw_chunks: list[str] = Field(default_factory=list)
    raw_token_count: int = 0
    compressed_context: str = ""
    compressed_token_count: int = 0
    compression_ratio: float = 0.0
    source_channel: str = "vector"
    latency_ms: float = 0.0


class GenerationResult(BaseModel):
    """Output of Stage 3 — Generation & Validation."""
    raw_output: str = ""
    severity: SeverityLevel = SeverityLevel.PASS
    format_valid: bool = True
    align_score: float = 1.0
    format_errors: list[str] = Field(default_factory=list)
    hallucination_flags: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0


class RepairResult(BaseModel):
    """Output of Stage 4 — Corrective Repair Loop."""
    final_output: str = ""
    iterations_used: int = 0
    max_iterations: int = 3
    repair_channel: RepairChannel = RepairChannel.VECTOR
    terminated_by_limit: bool = False
    latency_ms: float = 0.0


class PipelineResponse(BaseModel):
    """Full pipeline response returned to the caller."""
    query_id: str
    final_answer: str
    cache_hit: bool = False
    intent: QueryIntent = QueryIntent.SEMANTIC
    severity: SeverityLevel = SeverityLevel.PASS
    align_score: float = 1.0
    blocked: bool = False
    block_reason: Optional[str] = None
    repair_triggered: bool = False
    repair_iterations: int = 0
    token_economics: dict[str, Any] = Field(default_factory=dict)
    latency_breakdown: dict[str, float] = Field(default_factory=dict)
    total_latency_ms: float = 0.0
    # InputGuard security summary
    guard_risk_score: float = 0.0
    guard_verdict: str = "allow"


# ─────────────────────────────────────────────
# Configuration (loaded once at startup)
# ─────────────────────────────────────────────

class Config:
    # LLM
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    GEMINI_MAX_TOKENS: int = int(os.getenv("GEMINI_MAX_TOKENS", "2048"))

    # Neo4j
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # FAISS
    FAISS_INDEX_PATH: str = os.getenv("FAISS_INDEX_PATH", "./data/faiss.index")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

    # Pipeline limits
    MAX_REPAIR_ITERATIONS: int = int(os.getenv("MAX_REPAIR_ITERATIONS", "3"))
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    CONTEXT_TOKEN_BUDGET: int = int(os.getenv("CONTEXT_TOKEN_BUDGET", "2048"))

    # Validation thresholds
    ALIGN_SCORE_THRESHOLD: float = float(os.getenv("ALIGN_SCORE_THRESHOLD", "0.65"))
    FORMAT_VALIDATOR_STRICT: bool = os.getenv("FORMAT_VALIDATOR_STRICT", "true").lower() == "true"

    # ── InputGuard thresholds (all env-var driven, nothing hardcoded) ─────
    # Single-signal score that immediately triggers BLOCK (0.0–1.0)
    GUARD_BLOCK_SIGNAL_THRESHOLD: float = float(os.getenv("GUARD_BLOCK_SIGNAL_THRESHOLD", "0.80"))
    # Composite average score (across all 6 signals) that triggers BLOCK
    GUARD_BLOCK_COMPOSITE_THRESHOLD: float = float(os.getenv("GUARD_BLOCK_COMPOSITE_THRESHOLD", "0.50"))
    # Per-signal score that elevates verdict to WARN
    GUARD_WARN_SIGNAL_THRESHOLD: float = float(os.getenv("GUARD_WARN_SIGNAL_THRESHOLD", "0.35"))
    # Shannon entropy band for normal prose (bits per character)
    GUARD_ENTROPY_LOW: float = float(os.getenv("GUARD_ENTROPY_LOW", "3.5"))
    GUARD_ENTROPY_HIGH: float = float(os.getenv("GUARD_ENTROPY_HIGH", "5.5"))

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

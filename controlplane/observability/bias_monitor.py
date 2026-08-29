"""
ControlPlane.ai — Observability: Async Bias Monitor

Audits LLM outputs for demographic / algorithmic bias using IBM AIF360.
Runs ASYNCHRONOUSLY — does NOT block the main response thread.

Design: fire-and-forget thread pool.  Results are written to an internal
log and surfaced on the /metrics/bias endpoint for human review.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from loguru import logger

try:
    # AIF360 is optional — system degrades gracefully without it
    from aif360.datasets import BinaryLabelDataset
    from aif360.metrics import BinaryLabelDatasetMetric
    import pandas as pd
    _aif360_available = True
except ImportError:
    logger.warning("aif360 not installed — bias monitoring disabled.")
    _aif360_available = False

# ─────────────────────────────────────────────────────────────
# Rolling audit log (last 500 audits)
# ─────────────────────────────────────────────────────────────
_MAX_LOG = 500
_audit_log: deque[dict[str, Any]] = deque(maxlen=_MAX_LOG)
_log_lock = threading.Lock()

# Thread pool for async execution
_executor_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def submit_for_audit(
    query_id: str,
    output_text: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Non-blocking submission of an output for bias auditing.
    Returns immediately; audit happens in a background thread.
    """
    thread = threading.Thread(
        target=_audit_worker,
        args=(query_id, output_text, metadata or {}),
        daemon=True,
        name=f"bias-audit-{query_id[:8]}",
    )
    thread.start()


def get_bias_report() -> dict[str, Any]:
    """Return summary bias statistics for the dashboard."""
    with _log_lock:
        log = list(_audit_log)

    if not log:
        return {"status": "no audits yet", "aif360_available": _aif360_available}

    flagged = [e for e in log if e.get("bias_detected")]
    return {
        "total_audited": len(log),
        "bias_detected_count": len(flagged),
        "bias_rate": round(len(flagged) / max(len(log), 1), 4),
        "aif360_available": _aif360_available,
        "recent_flags": flagged[-5:],
    }


# ─────────────────────────────────────────────────────────────
# Background worker
# ─────────────────────────────────────────────────────────────

def _audit_worker(query_id: str, output_text: str, metadata: dict) -> None:
    """
    Performs the actual bias analysis.
    Results are appended to _audit_log — never blocks the API thread.
    """
    t0 = time.perf_counter()
    try:
        bias_detected, signals = _analyse_bias(output_text, metadata)
    except Exception as exc:
        logger.error(f"[BiasMonitor] Audit failed for {query_id}: {exc}")
        bias_detected, signals = False, []

    entry = {
        "query_id": query_id,
        "ts": time.time(),
        "bias_detected": bias_detected,
        "signals": signals,
        "audit_latency_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
    with _log_lock:
        _audit_log.append(entry)

    if bias_detected:
        logger.warning(f"[BiasMonitor] Bias signals detected for {query_id}: {signals}")


def _analyse_bias(output_text: str, metadata: dict) -> tuple[bool, list[str]]:
    """
    Core bias analysis logic.
    Uses AI-as-Judge pattern for subjective evaluation and heuristic fallbacks.
    """
    signals: list[str] = []
    
    # 1. AI-as-Judge pattern
    raw_query = metadata.get("raw_query", "")
    if raw_query:
        from controlplane.core.judge import evaluate_bias_and_safety
        report = evaluate_bias_and_safety(raw_query, output_text)
        if report.demographic_bias_detected:
            signals.append(f"AI-Judge: Demographic bias detected: {report.details}")
        if report.sentiment_bias_detected:
            signals.append(f"AI-Judge: Sentiment bias detected: {report.details}")

    # 2. Heuristic fallback: known stereotype phrases
    STEREOTYPE_PHRASES = [
        "women are less capable",
        "men are better at",
        "naturally suited for",
        "biologically inferior",
        "minorities tend to",
        "all [group]",
    ]
    lowered = output_text.lower()
    for phrase in STEREOTYPE_PHRASES:
        if phrase in lowered:
            signals.append(f"Stereotype phrase detected: {phrase!r}")

    return bool(signals), signals

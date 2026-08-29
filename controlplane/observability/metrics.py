"""
ControlPlane.ai — Observability: Metrics Collector

Tracks all pipeline telemetry:
  • Per-stage latency
  • Token economics (raw → compressed → LLM prompt cost)
  • Cache hit rate
  • Severity distribution (pass / warn / fail)
  • Repair loop utilisation

Exposes a Prometheus-compatible /metrics endpoint AND a
JSON snapshot endpoint consumed by the live dashboard.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

from loguru import logger

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    _prometheus_available = True
except ImportError:
    logger.warning("prometheus-client not installed — Prometheus metrics disabled.")
    _prometheus_available = False

# ─────────────────────────────────────────────────────────────
# Prometheus instruments
# ─────────────────────────────────────────────────────────────
if _prometheus_available:
    _request_count = Counter(
        "cp_requests_total", "Total pipeline requests", ["severity"]
    )
    _cache_hits = Counter("cp_cache_hits_total", "Cache hit count")
    _cache_misses = Counter("cp_cache_misses_total", "Cache miss count")
    _repair_iterations = Histogram(
        "cp_repair_iterations", "Repair loop iterations", buckets=[0, 1, 2, 3, 4]
    )
    _latency_hist = Histogram(
        "cp_pipeline_latency_ms",
        "End-to-end pipeline latency in ms",
        buckets=[50, 100, 200, 500, 1000, 2000, 5000],
    )
    _token_savings_gauge = Gauge(
        "cp_token_savings_ratio", "Average token compression ratio"
    )
    _align_score_gauge = Gauge("cp_align_score_last", "Most recent AlignScore")


# ─────────────────────────────────────────────────────────────
# In-memory rolling window (last 1000 requests)
# ─────────────────────────────────────────────────────────────
_MAX_WINDOW = 1000
_lock = threading.Lock()

_records: deque[dict[str, Any]] = deque(maxlen=_MAX_WINDOW)
_cumulative: dict[str, float] = defaultdict(float)
_counters: dict[str, int] = defaultdict(int)


# ─────────────────────────────────────────────────────────────
# Public API — called by the pipeline orchestrator
# ─────────────────────────────────────────────────────────────

def record_request(
    query_id: str,
    severity: str,
    cache_hit: bool,
    total_latency_ms: float,
    latency_breakdown: dict[str, float],
    token_economics: dict[str, Any],
    repair_iterations: int,
    align_score: float,
    repair_triggered: bool = False,
    guard_risk_score: float = 0.0,
    guard_verdict: str = "allow",
) -> None:
    """Record a completed pipeline request."""
    record = {
        "query_id": query_id,
        "ts": time.time(),
        "severity": severity,
        "cache_hit": cache_hit,
        "total_latency_ms": total_latency_ms,
        "latency_breakdown": latency_breakdown,
        "token_economics": token_economics,
        "repair_iterations": repair_iterations,
        "align_score": align_score,
        "guard_risk_score": guard_risk_score,
        "guard_verdict": guard_verdict,
    }

    with _lock:
        _records.append(record)
        _counters["total"] += 1
        _counters[f"severity_{severity}"] += 1
        _counters["cache_hit" if cache_hit else "cache_miss"] += 1
        if repair_triggered:
            _counters["repairs"] += 1
        _cumulative["total_latency_ms"] += total_latency_ms
        _cumulative["align_score"] += align_score
        raw = token_economics.get("raw_token_count", 0)
        compressed = token_economics.get("compressed_token_count", 0)
        if raw > 0:
            _cumulative["token_savings"] += 1 - compressed / raw

    if _prometheus_available:
        _request_count.labels(severity=severity).inc()
        ((_cache_hits if cache_hit else _cache_misses)).inc()
        _latency_hist.observe(total_latency_ms)
        _repair_iterations.observe(repair_iterations)
        _align_score_gauge.set(align_score)
        n = _counters["total"]
        _token_savings_gauge.set(_cumulative["token_savings"] / max(n, 1))

def update_request_severity(query_id: str, new_severity: str) -> None:
    """Update the severity of a past request (e.g., after HITL review)."""
    with _lock:
        for record in _records:
            if record["query_id"] == query_id:
                old_severity = record["severity"]
                if old_severity == new_severity:
                    return
                record["severity"] = new_severity
                _counters[f"severity_{old_severity}"] = max(0, _counters[f"severity_{old_severity}"] - 1)
                _counters[f"severity_{new_severity}"] += 1
                return


def get_dashboard_snapshot() -> dict[str, Any]:
    """Return a JSON-serialisable snapshot for the live dashboard."""
    with _lock:
        n = _counters["total"] or 1  # avoid div-by-zero
        recent = list(_records)[-10:]  # last 10 for sparklines

        return {
            "total_requests": _counters["total"],
            "severity_distribution": {
                "pass": _counters["severity_pass"],
                "warn": _counters["severity_warn"],
                "fail": _counters["severity_fail"],
                "quarantine": _counters["severity_quarantine"],
                "redact": _counters["severity_redact"],
            },
            "cache": {
                "hits": _counters["cache_hit"],
                "misses": _counters["cache_miss"],
                "hit_rate": round(_counters["cache_hit"] / n, 4),
            },
            "latency": {
                "avg_ms": round(_cumulative["total_latency_ms"] / n, 2),
            },
            "token_economics": {
                "avg_compression_ratio": max(round(_cumulative["token_savings"] / n, 4), 0.0),
            },
            "grounding": {
                "avg_align_score": round(_cumulative["align_score"] / n, 4),
            },
            "repair_loop": {
                "requests_repaired": _counters["repairs"],
            },
            "recent_requests": recent,
        }


def prometheus_output() -> tuple[bytes, str]:
    """Return raw Prometheus text output for /metrics endpoint."""
    if not _prometheus_available:
        return b"# Prometheus not available\n", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST

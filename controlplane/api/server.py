"""
ControlPlane.ai — FastAPI Server

Endpoints:
  GET  /               — redirects to the interactive dashboard
  POST /query          — main pipeline entry point
  GET  /health         — liveness probe
  GET  /metrics        — Prometheus scrape endpoint
  GET  /metrics/dashboard — JSON snapshot for the live dashboard
  GET  /metrics/bias   — bias audit report
  GET  /cache/stats    — semantic cache statistics
  GET  /dashboard/     — interactive web UI (static files)
"""

from __future__ import annotations

import os
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Any, Optional

from loguru import logger

from controlplane.pipeline import run_pipeline
from controlplane.observability.metrics import get_dashboard_snapshot, prometheus_output
from controlplane.observability.bias_monitor import get_bias_report
from controlplane.cache.semantic_cache import cache_stats
from controlplane.core.governance import Governance

# ─────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="ControlPlane.ai",
    description=(
        "Intelligent LLM middleware: ingress filtering, adaptive retrieval, "
        "hallucination validation, and corrective repair."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# Startup routines
# ─────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """Load the pre-built FAISS index into memory on server start."""
    from controlplane.core.retrieval import load_faiss_index
    import json
    
    faiss_path = "./data/faiss.index"
    meta_path = "./data/faiss_meta.json"
    
    if os.path.exists(faiss_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta_data = json.load(f)
            
            texts = meta_data.get("texts", [])
            metadata = meta_data.get("metadata", [])
            
            load_faiss_index(faiss_path, texts, metadata)
        except Exception as exc:
            logger.error(f"Failed to load FAISS index: {exc}")
    else:
        logger.warning(f"FAISS index files not found at {faiss_path}. Vector retrieval will return mock chunks.")


# ─────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096, description="Raw user query")
    top_k: int = Field(default=8, ge=1, le=50, description="Number of chunks to retrieve")
    expected_format: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional JSON schema for output format validation",
    )


class QueryResponse(BaseModel):
    query_id: str
    answer: str
    cache_hit: bool
    intent: str
    severity: str
    align_score: float
    blocked: bool
    block_reason: Optional[str]
    repair_triggered: bool
    repair_iterations: int
    token_economics: dict[str, Any]
    latency_ms: dict[str, float]
    total_latency_ms: float
    guard_risk_score: float = 0.0
    guard_verdict: str = "allow"


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to the interactive dashboard."""
    return RedirectResponse(url="/dashboard/")


@app.post("/query", response_model=QueryResponse, summary="Submit a query to the pipeline")
async def query_endpoint(req: QueryRequest) -> QueryResponse:
    """
    1. Checks the semantic cache.
    2. Runs ingress (intent classification + PII masking + constraint decomposition).
    3. Routes to vector or graph retrieval with context compression.
    4. Generates a response and validates it for format + grounding.
    5. If validation fails, triggers the corrective repair loop.
    """
    try:
        result = run_pipeline(
            raw_query=req.query,
            expected_format=req.expected_format,
            top_k=req.top_k,
        )
    except Exception as exc:
        logger.exception(f"Pipeline error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    return QueryResponse(
        query_id=result.query_id,
        answer=result.final_answer,
        cache_hit=result.cache_hit,
        intent=result.intent.value if result.intent else "semantic",
        severity=result.severity.value if result.severity else "pass",
        align_score=result.align_score,
        blocked=result.blocked,
        block_reason=result.block_reason,
        repair_triggered=result.repair_triggered,
        repair_iterations=result.repair_iterations,
        token_economics=result.token_economics,
        latency_ms=result.latency_breakdown,
        total_latency_ms=result.total_latency_ms,
        guard_risk_score=result.guard_risk_score,
        guard_verdict=result.guard_verdict,
    )


@app.get("/health", summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok", "service": "controlplane.ai"}


@app.get("/metrics", summary="Prometheus metrics scrape endpoint")
async def prometheus_metrics() -> Response:
    data, content_type = prometheus_output()
    return Response(content=data, media_type=content_type)


@app.get("/metrics/dashboard", summary="Live dashboard JSON snapshot")
async def dashboard_snapshot() -> JSONResponse:
    return JSONResponse(get_dashboard_snapshot())


@app.get("/metrics/bias", summary="Bias audit report")
async def bias_report() -> JSONResponse:
    return JSONResponse(get_bias_report())


@app.get("/cache/stats", summary="Semantic cache statistics")
async def cache_statistics() -> JSONResponse:
    return JSONResponse(cache_stats())


class HitlResolveRequest(BaseModel):
    action: str = Field(..., description="Action to take: approve, block, or redact")
    reviewed_by: str = Field("admin", description="ID of the human reviewer")

@app.get("/api/hitl", summary="Get pending HITL queue")
async def get_hitl():
    items = Governance.get_pending_hitl()
    return JSONResponse({"items": items})

@app.post("/api/hitl/{query_id}/resolve", summary="Resolve a HITL item")
async def resolve_hitl_item(query_id: str, req: HitlResolveRequest):
    success = Governance.resolve_hitl(query_id, req.action, req.reviewed_by)
    if success:
        return {"status": "ok", "action": req.action}
    raise HTTPException(status_code=404, detail="Item not found or already resolved")


# ─────────────────────────────────────────────────────────────
# Mount static dashboard (MUST be AFTER all API routes)
# ─────────────────────────────────────────────────────────────
_dashboard_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "dashboard",
)
if os.path.isdir(_dashboard_dir):
    app.mount("/dashboard", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")
    logger.info(f"Dashboard mounted from {_dashboard_dir}")
else:
    logger.warning(f"Dashboard directory not found at {_dashboard_dir}")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "controlplane.api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

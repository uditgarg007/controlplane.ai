"""
ControlPlane.ai — Pipeline Orchestrator

Connects all four stages + the parallel cache and observability layers
into a single, clean run_pipeline() call.

This is the only module that imports from all stages — all other modules
are completely isolated.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from loguru import logger

from controlplane.config import PipelineResponse, QueryIntent, SeverityLevel, UserContext
from controlplane.core.governance import PolicyEngine, Governance
from controlplane.core.ingress import run_ingress
from controlplane.core.retrieval import run_retrieval
from controlplane.core.generation import run_generation
from controlplane.core.repair import run_repair_loop
from controlplane.cache.semantic_cache import cache_lookup, cache_store
from controlplane.observability.metrics import record_request
from controlplane.observability.bias_monitor import submit_for_audit


def run_pipeline(
    raw_query: str,
    expected_format: dict[str, Any] | None = None,
    top_k: int = 8,
    user_context: Optional[UserContext] = None,
    session_id: Optional[str] = None,
) -> PipelineResponse:
    """
    Full ControlPlane.ai pipeline for a single query.
    """
    pipeline_t0 = time.perf_counter()
    query_id = str(uuid.uuid4())
    latency: dict[str, float] = {}

    if user_context is None:
        user_context = UserContext()
    
    policy = PolicyEngine.get_policy(user_context)
    logger.info(f"[Pipeline] START query_id={query_id} | Policy={policy.name}")

    # Stage 0: Semantic Cache Check
    cached_answer = cache_lookup(raw_query)
    if cached_answer:
        total_ms = _elapsed_ms(pipeline_t0)
        logger.info(f"[Pipeline] CACHE HIT — {total_ms:.1f} ms")
        
        # When hitting cache, we save 100% of the tokens that would have been used.
        # Estimate the raw tokens that would have been retrieved (e.g. 5x the answer length).
        estimated_raw = max(100, int((len(raw_query) + len(cached_answer)) / 0.75) * 5)
        
        resp = PipelineResponse(
            query_id=query_id,
            final_answer=cached_answer,
            cache_hit=True,
            total_latency_ms=total_ms,
            latency_breakdown={"cache_lookup": total_ms},
            token_economics={
                "raw_token_count": estimated_raw,
                "compressed_token_count": 0,
                "compression_ratio": 1.0,
                "source_channel": "cache"
            }
        )
        _emit_metrics(resp, align_score=1.0)
        return resp

    # Stage 1: Ingress
    ingress = run_ingress(raw_query, policy=policy, user_context=user_context)
    latency["ingress"] = ingress.latency_ms

    if session_id:
        from controlplane.session import SessionManager
        session_mgr = SessionManager()
        cum_risk = session_mgr.accumulate_risk(session_id, ingress.guard_risk_score)
        logger.info(f"[Pipeline] Session {session_id} cumulative risk: {cum_risk:.2f}")
        # Block if compounding risk gets too high across the session
        if cum_risk > 2.0:
            ingress.blocked = True
            ingress.block_reason = "Compounding session risk exceeded maximum threshold (2.0)."
            ingress.guard_risk_score = cum_risk
            
    if ingress.blocked:
        total_ms = _elapsed_ms(pipeline_t0)
        logger.warning(f"[Pipeline] BLOCKED — {ingress.block_reason}")
        
        triggered_signals = [s["name"] for s in ingress.guard_signals if s.get("triggered")]
        signal_summary = ", ".join(triggered_signals) if triggered_signals else "jailbreak pattern"
        flagged_answer = (
            f"🚫 Request Flagged & Blocked\n\n"
            f"This request was intercepted before reaching the LLM.\n\n"
            f"Reason: {ingress.block_reason}\n\n"
            f"Security signals triggered: {signal_summary}\n"
            f"Risk score: {ingress.guard_risk_score:.2f} / 1.00"
        )
        Governance.log_audit(query_id, user_context.user_id, "BLOCKED", ingress.block_reason or "")
        estimated_raw_tokens = max(300, len(raw_query) * 5)
        resp = PipelineResponse(
            query_id=query_id,
            final_answer=flagged_answer,
            blocked=True,
            block_reason=ingress.block_reason,
            intent=ingress.intent,
            severity=SeverityLevel.FAIL,
            guard_risk_score=ingress.guard_risk_score,
            guard_verdict=ingress.guard_verdict,
            total_latency_ms=total_ms,
            latency_breakdown=latency,
            token_economics={
                "raw_token_count": estimated_raw_tokens,
                "compressed_token_count": 0,
                "compression_ratio": 1.0,
                "source_channel": "guard_blocked"
            }
        )
        _emit_metrics(resp, align_score=0.0)
        return resp

    # Stage 2: Retrieval Routing
    retrieval = run_retrieval(ingress, top_k=top_k)
    latency["retrieval"] = retrieval.latency_ms

    # Stage 3: Generation
    generation_kwargs = {"expected_format": expected_format, "policy": policy}
    if session_id:
        generation_kwargs["session_messages"] = session_mgr.get_messages(session_id)
        
    generation = run_generation(ingress, retrieval, **generation_kwargs)
    latency["generation"] = generation.latency_ms

    repair_triggered = False
    repair_iterations = 0

    output_lower = generation.raw_output.lower() if generation.raw_output else ""
    is_privacy_or_error = (
        "redacted for privacy" in output_lower
        or "cannot proceed" in output_lower
        or "[llm error]" in output_lower
        or "[llm unavailable]" in output_lower
        or "[llm rate limit exceeded]" in output_lower
    )

    is_intentional_fail = (
        generation.severity == SeverityLevel.FAIL
        and generation.format_valid
        and not generation.hallucination_flags
        and is_privacy_or_error
    )

    if (generation.severity in [SeverityLevel.FAIL, SeverityLevel.WARN]) and not is_intentional_fail:
        repair_triggered = True
        repair = run_repair_loop(ingress, generation, retrieval, policy=policy)
        latency["repair"] = repair.latency_ms
        repair_iterations = repair.iterations_used
        final_answer = repair.final_output
        
        # 3 explicit repair loop outcomes:
        # 1. Repaired successfully -> mark as PASS
        # 2. Blocked / Unsafe -> mark as FAIL
        # 3. Further human review needed -> mark as QUARANTINE
        if repair.status == "blocked" or repair.final_severity == SeverityLevel.FAIL:
            final_severity = SeverityLevel.FAIL
        elif repair.status == "human_needed" or repair.final_severity == SeverityLevel.QUARANTINE or repair.terminated_by_limit:
            final_severity = SeverityLevel.QUARANTINE
        else:
            final_severity = SeverityLevel.PASS
    else:
        final_answer = generation.raw_output
        final_severity = generation.severity

    if final_severity == SeverityLevel.WARN and policy.quarantine_on_warn:
        final_severity = SeverityLevel.QUARANTINE

    if final_severity == SeverityLevel.QUARANTINE:
        Governance.enqueue_hitl(query_id, raw_query, final_answer, final_severity.value, policy.name)
        Governance.log_audit(query_id, user_context.user_id, "QUARANTINED", "Response flagged for HITL review.")
        final_answer = "[QUARANTINED] This response has been flagged for human review due to policy constraints."

    # Cache Store
    _error_prefixes = ("[LLM ERROR]", "[LLM UNAVAILABLE]", "[MOCK", "[LLM RATE LIMIT", "[QUARANTINED]")
    _answer_lower = final_answer.lower() if final_answer else ""
    _is_refusal = "insufficient context" in _answer_lower or "redacted for privacy" in _answer_lower
    if (
        final_answer 
        and final_severity not in (SeverityLevel.FAIL, SeverityLevel.QUARANTINE)
        and not _is_refusal
        and not final_answer.startswith(_error_prefixes)
    ):
        cache_store(raw_query, final_answer)
        if session_id:
            session_mgr.add_message(session_id, "user", raw_query)
            session_mgr.add_message(session_id, "assistant", final_answer)

    submit_for_audit(query_id, final_answer, metadata={"raw_query": raw_query})

    total_ms = _elapsed_ms(pipeline_t0)
    latency["total"] = total_ms

    token_economics = {
        "raw_token_count": retrieval.raw_token_count,
        "compressed_token_count": retrieval.compressed_token_count,
        "compression_ratio": retrieval.compression_ratio,
        "source_channel": retrieval.source_channel,
    }

    response = PipelineResponse(
        query_id=query_id,
        final_answer=final_answer,
        cache_hit=False,
        intent=ingress.intent,
        severity=final_severity,
        align_score=generation.align_score,
        blocked=False,
        repair_triggered=repair_triggered,
        repair_iterations=repair_iterations,
        token_economics=token_economics,
        latency_breakdown=latency,
        total_latency_ms=total_ms,
        guard_risk_score=ingress.guard_risk_score,
        guard_verdict=ingress.guard_verdict,
    )

    _emit_metrics(response, align_score=generation.align_score)
    logger.info(
        f"[Pipeline] DONE query_id={query_id} | "
        f"severity={final_severity} | {total_ms:.1f} ms | "
        f"repair={repair_triggered} ({repair_iterations} iters)"
    )
    return response


def _emit_metrics(resp: PipelineResponse, align_score: float) -> None:
    record_request(
        query_id=resp.query_id,
        severity=resp.severity.value if resp.severity else "pass",
        cache_hit=resp.cache_hit,
        total_latency_ms=resp.total_latency_ms,
        latency_breakdown=resp.latency_breakdown,
        token_economics=resp.token_economics,
        repair_iterations=resp.repair_iterations,
        align_score=align_score,
        repair_triggered=resp.repair_triggered,
        guard_risk_score=resp.guard_risk_score,
        guard_verdict=resp.guard_verdict,
    )

def _elapsed_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)

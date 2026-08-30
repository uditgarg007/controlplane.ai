"""
ControlPlane.ai — Stage 4: Corrective Repair Loop

Responsibilities:
  1. Failure analysis  — a "Judge" LLM evaluates WHY the generation failed
                         (bad retrieval? hallucination? format error?).
  2. Query rewriting   — the rewritten query is broader / differently phrased
                         to recover from retrieval gaps.
  3. Re-retrieval      — triggers a new retrieval pass (vector, graph, or web).
  4. Bounded iteration — hard cap on iterations (default: 3) prevents runaway
                         API spend.  The loop terminates on first PASS or on limit.

Frameworks: CRAG (Corrective RAG) + Self-RAG evaluation signals.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from controlplane.config import (
    Config,
    GenerationResult,
    IngressResult,
    PolicyProfile,
    RepairChannel,
    RepairResult,
    RetrievalResult,
    SeverityLevel,
)


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def run_repair_loop(
    ingress: IngressResult,
    failed_generation: GenerationResult,
    retrieval: RetrievalResult,
    policy: PolicyProfile | None = None,
) -> RepairResult:
    """
    Entry point for Stage 4.

    Iterates up to Config.MAX_REPAIR_ITERATIONS times:
      1. Judge analyses the failure.
      2. Query is rewritten.
      3. Re-retrieval + re-generation happen.
      4. If severity == PASS → exit loop early (repaired -> PASS).
      5. If severity == FAIL with explicit refusal/block → exit (blocked -> FAIL).
      6. If loop exhausted → exit with QUARANTINE (human needed -> QUARANTINE).

    Returns RepairResult with final severity and status.
    """
    # Inline imports to avoid circular dependency
    from controlplane.core.generation import run_generation
    from controlplane.core.retrieval import run_retrieval, _web_retrieve

    t0 = time.perf_counter()
    max_iter = Config.MAX_REPAIR_ITERATIONS
    terminated_by_limit = False

    current_ingress = ingress
    current_retrieval = retrieval
    current_generation = failed_generation
    channel = RepairChannel.VECTOR

    final_severity = SeverityLevel.PASS
    status = "pass"

    for iteration in range(1, max_iter + 1):
        logger.info(f"[Repair Loop] Iteration {iteration}/{max_iter}")

        # ── 1. Judge: diagnose the failure ──────────────────────
        failure_reason = _judge_failure(current_generation)
        logger.info(f"[Repair Loop] Failure reason: {failure_reason}")

        # ── 2. Determine repair channel ──────────────────────────
        channel = _select_repair_channel(failure_reason, iteration)
        logger.info(f"[Repair Loop] Repair channel: {channel}")

        # ── 3. Rewrite the query ─────────────────────────────────
        rewritten_query = _rewrite_query(
            original_query=current_ingress.clean_query,
            failure_reason=failure_reason,
            attempt=iteration,
        )
        logger.info(f"[Repair Loop] Rewritten query: {rewritten_query!r}")

        # ── 4. Patch ingress with new query ──────────────────────
        current_ingress = current_ingress.model_copy(
            update={"clean_query": rewritten_query}
        )

        # ── 5. Re-retrieve ───────────────────────────────────────
        if channel == RepairChannel.WEB:
            current_retrieval = _web_retrieve(rewritten_query)
        else:
            current_retrieval = run_retrieval(current_ingress)

        # ── 6. Re-generate & validate ────────────────────────────
        current_generation = run_generation(current_ingress, current_retrieval, policy=policy)

        # ── 7. Evaluate iteration outcome ────────────────────────
        if current_generation.severity == SeverityLevel.PASS:
            logger.info(f"[Repair Loop] Successfully repaired in iteration {iteration}.")
            final_severity = SeverityLevel.PASS
            status = "pass"
            break

        out_lower = (current_generation.raw_output or "").lower()
        if (
            current_generation.severity == SeverityLevel.FAIL
            and any(marker in out_lower for marker in ["redacted for privacy", "cannot proceed", "[llm error]", "harmful", "blocked"])
        ):
            logger.warning(f"[Repair Loop] Generation blocked / refused during repair iteration {iteration}.")
            final_severity = SeverityLevel.FAIL
            status = "blocked"
            break
    else:
        # Loop exhausted without PASS
        terminated_by_limit = True
        logger.warning(
            f"[Repair Loop] Bounded iteration limit ({max_iter}) reached. "
            "Flagging for Human-in-the-Loop review."
        )
        if current_generation.severity == SeverityLevel.FAIL:
            final_severity = SeverityLevel.FAIL
            status = "blocked"
        else:
            final_severity = SeverityLevel.QUARANTINE
            status = "human_needed"

    return RepairResult(
        final_output=current_generation.raw_output,
        iterations_used=iteration,
        max_iterations=max_iter,
        repair_channel=channel,
        terminated_by_limit=terminated_by_limit,
        final_severity=final_severity,
        status=status,
        latency_ms=_elapsed_ms(t0),
    )


# ─────────────────────────────────────────────────────────────
# Judge — CRAG / Self-RAG style failure analysis
# ─────────────────────────────────────────────────────────────

def _judge_failure(gen: GenerationResult) -> str:
    """
    Diagnose why the generation failed.

    Returns a structured string tag used downstream to select the repair strategy.

    Decision tree (priority order):
      HALLUCINATION   — AlignScore below threshold
      FORMAT_ERROR    — structural / schema validation failed
      EMPTY_OUTPUT    — LLM returned nothing useful
      AMBIGUOUS       — multiple moderate issues
    """
    if gen.hallucination_flags:
        return "HALLUCINATION"
    if not gen.format_valid:
        if any("Empty output" in e for e in gen.format_errors):
            return "EMPTY_OUTPUT"
        return "FORMAT_ERROR"
    if gen.align_score < Config.ALIGN_SCORE_THRESHOLD:
        return "HALLUCINATION"
    return "AMBIGUOUS"


# ─────────────────────────────────────────────────────────────
# Repair channel selection
# ─────────────────────────────────────────────────────────────

def _select_repair_channel(failure_reason: str, iteration: int) -> RepairChannel:
    """
    Choose the retrieval channel for this repair attempt.

    Strategy:
      Iteration 1 — try the other DB channel (graph ↔ vector).
      Iteration 2 — escalate to web search for fresh information.
      Iteration 3 — fallback to vector again (broader search).
    """
    if iteration == 1:
        # If hallucination: the retrieved context was bad → switch channel
        if failure_reason == "HALLUCINATION":
            return RepairChannel.GRAPH
        return RepairChannel.VECTOR
    elif iteration == 2:
        return RepairChannel.WEB
    else:
        return RepairChannel.VECTOR


# ─────────────────────────────────────────────────────────────
# Query rewriting
# ─────────────────────────────────────────────────────────────

def _rewrite_query(original_query: str, failure_reason: str, attempt: int) -> str:
    """
    Programmatically rewrite the query to broaden scope and recover from failures.

    In production: call an LLM rewriter.  Here we apply deterministic strategies
    that work without an extra API call to keep latency and cost minimal.
    """
    strategies: dict[str, list[str]] = {
        "HALLUCINATION": [
            f"Explain in simple terms: {original_query}",
            f"What are the key facts about: {original_query}",
            f"Provide a grounded, source-cited answer to: {original_query}",
        ],
        "FORMAT_ERROR": [
            f"Answer concisely: {original_query}",
            f"Respond in plain prose (no JSON, no lists): {original_query}",
            f"Give a one-paragraph answer to: {original_query}",
        ],
        "EMPTY_OUTPUT": [
            f"What is known about: {original_query}",
            f"Summarise available information on: {original_query}",
            f"Background context for: {original_query}",
        ],
        "AMBIGUOUS": [
            f"Rephrase and answer: {original_query}",
            f"Alternative perspective on: {original_query}",
            f"Step-by-step answer to: {original_query}",
        ],
    }

    options = strategies.get(failure_reason, strategies["AMBIGUOUS"])
    idx = min(attempt - 1, len(options) - 1)   # clamp to last strategy
    return options[idx]


# ─────────────────────────────────────────────────────────────
# Web retrieval channel (now in retrieval.py)
# ─────────────────────────────────────────────────────────────


def _elapsed_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)

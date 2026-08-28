"""
ControlPlane.ai — Stage 3 & 4 Tests: Generation & Repair Loop

Tests verify:
  1. Format validator correctly flags empty / sycophantic / malformed output.
  2. Severity routing returns FAIL on hallucination flags.
  3. Severity routing returns PASS on clean output.
  4. Jaccard trigram grounding score is computed correctly.
  5. Repair loop terminates at bounded iteration limit.
  6. Repair loop exits early on first PASS.
  7. Failure reason (Judge) is correctly diagnosed.
"""

from __future__ import annotations

import pytest

from controlplane.core.generation import (
    _validate_format,
    _route_severity,
    _jaccard_trigram_score,
    _check_grounding,
)
from controlplane.core.repair import (
    _judge_failure,
    _rewrite_query,
    _select_repair_channel,
    run_repair_loop,
)
from controlplane.config import (
    GenerationResult,
    IngressResult,
    QueryIntent,
    RepairChannel,
    RetrievalResult,
    SeverityLevel,
)


# ─────────────────────────────────────────────────────────────
# Format Validation
# ─────────────────────────────────────────────────────────────

class TestFormatValidation:
    def test_empty_output_fails(self):
        valid, errors = _validate_format("", None)
        assert not valid
        assert any("Empty" in e for e in errors)

    def test_whitespace_only_fails(self):
        valid, errors = _validate_format("   \n\t  ", None)
        assert not valid

    def test_too_short_fails(self):
        valid, errors = _validate_format("ok", None)
        assert not valid
        assert any("too short" in e for e in errors)

    def test_sycophantic_prefix_flagged(self):
        valid, errors = _validate_format("Sure! Here is the answer you asked for.", None)
        assert not valid

    def test_valid_prose_passes(self):
        text = "The transformer architecture uses self-attention mechanisms to model long-range dependencies."
        valid, errors = _validate_format(text, None)
        assert valid
        assert errors == []

    def test_valid_json_with_schema_passes(self):
        output = '```json\n{"name": "Alice", "age": 30}\n```'
        schema = {"required": ["name", "age"], "types": {"name": "string", "age": "number"}}
        valid, errors = _validate_format(output, schema)
        assert valid

    def test_missing_required_field_fails(self):
        output = '{"name": "Alice"}'
        schema = {"required": ["name", "age"]}
        valid, errors = _validate_format(output, schema)
        assert not valid
        assert any("age" in e for e in errors)


# ─────────────────────────────────────────────────────────────
# Severity Routing Engine
# ─────────────────────────────────────────────────────────────

class TestSeverityRouter:
    def test_fail_on_hallucination(self):
        severity = _route_severity(
            raw_output="Some hallucinated answer.",
            format_valid=True,
            align_score=0.4,   # below threshold 0.65
            format_errors=[],
            hallucination_flags=["AlignScore 0.4 < threshold"],
        )
        assert severity == SeverityLevel.FAIL

    def test_fail_on_format_error(self):
        severity = _route_severity(
            raw_output="{invalid json}",
            format_valid=False,
            align_score=0.9,
            format_errors=["Missing required field: name"],
            hallucination_flags=[],
        )
        assert severity == SeverityLevel.FAIL

    def test_pass_on_clean_output(self):
        severity = _route_severity(
            raw_output="The capital of France is Paris.",
            format_valid=True,
            align_score=0.95,
            format_errors=[],
            hallucination_flags=[],
        )
        assert severity == SeverityLevel.PASS

    def test_warn_on_borderline_score(self):
        severity = _route_severity(
            raw_output="The answer is approximately correct.",
            format_valid=True,
            align_score=0.68,   # threshold=0.65, warn zone = [0.65, 0.75)
            format_errors=[],
            hallucination_flags=[],
        )
        assert severity == SeverityLevel.WARN


# ─────────────────────────────────────────────────────────────
# Jaccard Trigram Grounding Score
# ─────────────────────────────────────────────────────────────

class TestJaccardGrounding:
    def test_identical_texts_score_one(self):
        text = "the quick brown fox jumps over the lazy dog"
        score = _jaccard_trigram_score(text, text)
        assert score == 1.0

    def test_completely_different_texts_score_zero(self):
        a = "red green blue yellow"
        b = "quantum physics relativity energy"
        score = _jaccard_trigram_score(a, b)
        assert score == 0.0

    def test_partial_overlap_between_zero_and_one(self):
        a = "the quick brown fox jumps over the hedge"
        b = "the quick brown fox jumps over the lazy dog"
        score = _jaccard_trigram_score(a, b)
        assert 0.0 < score < 1.0

    def test_empty_inputs_return_one(self):
        assert _jaccard_trigram_score("", "") == 1.0


# ─────────────────────────────────────────────────────────────
# Stage 4: Repair Loop
# ─────────────────────────────────────────────────────────────

def _make_failed_gen(reason: str = "HALLUCINATION") -> GenerationResult:
    """Helper: construct a GenerationResult that mimics a failed generation."""
    if reason == "HALLUCINATION":
        return GenerationResult(
            raw_output="The answer is 42 and many other facts I invented.",
            severity=SeverityLevel.FAIL,
            format_valid=True,
            align_score=0.20,
            hallucination_flags=["AlignScore 0.2 < threshold 0.65"],
        )
    elif reason == "FORMAT_ERROR":
        return GenerationResult(
            raw_output="",
            severity=SeverityLevel.FAIL,
            format_valid=False,
            align_score=0.9,
            format_errors=["Empty output — LLM returned nothing."],
        )
    return GenerationResult(
        raw_output="vague answer",
        severity=SeverityLevel.FAIL,
        format_valid=False,
        align_score=0.30,
        format_errors=["Output too short"],
        hallucination_flags=["AlignScore 0.3 < threshold"],
    )


def _make_ingress() -> IngressResult:
    return IngressResult(
        original_query="What is the boiling point of water on Mars?",
        clean_query="What is the boiling point of water on Mars?",
        intent=QueryIntent.SEMANTIC,
        positive_vectors=["boiling point water Mars"],
        negative_constraints=[],
        metadata_filters={},
    )


def _make_retrieval() -> RetrievalResult:
    return RetrievalResult(
        raw_chunks=["Mars has very low atmospheric pressure."],
        raw_token_count=10,
        compressed_context="Mars atmospheric pressure is very low.",
        compressed_token_count=8,
        compression_ratio=0.2,
        source_channel="vector",
    )


class TestJudge:
    def test_hallucination_diagnosed(self):
        gen = _make_failed_gen("HALLUCINATION")
        reason = _judge_failure(gen)
        assert reason == "HALLUCINATION"

    def test_empty_output_diagnosed(self):
        gen = _make_failed_gen("FORMAT_ERROR")
        reason = _judge_failure(gen)
        assert reason == "EMPTY_OUTPUT"


class TestQueryRewriter:
    def test_produces_different_query(self):
        original = "What is the boiling point of water on Mars?"
        rewritten = _rewrite_query(original, "HALLUCINATION", attempt=1)
        assert rewritten != original

    def test_strategies_differ_across_attempts(self):
        original = "What is the boiling point of water on Mars?"
        r1 = _rewrite_query(original, "HALLUCINATION", attempt=1)
        r2 = _rewrite_query(original, "HALLUCINATION", attempt=2)
        assert r1 != r2


class TestChannelSelection:
    def test_hallucination_routes_to_graph_first(self):
        channel = _select_repair_channel("HALLUCINATION", iteration=1)
        assert channel == RepairChannel.GRAPH

    def test_second_iteration_routes_to_web(self):
        channel = _select_repair_channel("HALLUCINATION", iteration=2)
        assert channel == RepairChannel.WEB

    def test_third_iteration_falls_back_to_vector(self):
        channel = _select_repair_channel("HALLUCINATION", iteration=3)
        assert channel == RepairChannel.VECTOR


class TestRepairLoop:
    def test_loop_terminates_within_limit(self):
        """The repair loop must NEVER exceed MAX_REPAIR_ITERATIONS."""
        from controlplane import config
        # Override limit to 2 for speed
        original_limit = config.Config.MAX_REPAIR_ITERATIONS
        config.Config.MAX_REPAIR_ITERATIONS = 2

        ingress = _make_ingress()
        gen = _make_failed_gen("HALLUCINATION")
        retrieval = _make_retrieval()

        result = run_repair_loop(ingress, gen, retrieval)

        config.Config.MAX_REPAIR_ITERATIONS = original_limit
        assert result.iterations_used <= 2

    def test_result_has_output(self):
        """Repair loop must always produce a non-None final_output."""
        ingress = _make_ingress()
        gen = _make_failed_gen("HALLUCINATION")
        retrieval = _make_retrieval()

        result = run_repair_loop(ingress, gen, retrieval)
        assert result.final_output is not None

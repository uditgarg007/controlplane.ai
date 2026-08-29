"""
ControlPlane.ai — Stage 1: Ingress & Decomposer

Responsibilities:
  1. Intent Classification  — routes the query to the right retrieval path.
  2. PII Masking            — strips personal data before it enters the system.
  3. Constraint Decomposition — separates positive intent vectors from negative
                                hard constraints (metadata pre-filters).

Design principle: This is the "pre-flight check."  Nothing reaches the databases
until it has passed through here.  Latency budget: ≤ 30 ms on CPU.
"""

from __future__ import annotations

import re
import time
import unicodedata
import uuid
from typing import Any

from loguru import logger

from controlplane.config import Config, IngressResult, QueryIntent, PolicyProfile, UserContext
from controlplane.core import input_guard as _guard

# ─────────────────────────────────────────────────────────────
# Optional heavy imports — gracefully degrade if not installed.
# In production, both libraries must be present.
# ─────────────────────────────────────────────────────────────
try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine

    _pii_analyzer = AnalyzerEngine()
    _pii_anonymizer = AnonymizerEngine()
    _presidio_available = True
except ImportError:
    logger.warning("presidio not installed — PII detection disabled.")
    _presidio_available = False

try:
    from transformers import pipeline as hf_pipeline

    _intent_classifier = hf_pipeline(
        "zero-shot-classification",
        model="facebook/bart-large-mnli",   # swap to ModernBERT once publicly available
        device=-1,                          # CPU; set to 0 for GPU
    )
    _hf_available = True
except Exception as exc:
    logger.warning(f"HuggingFace pipeline unavailable ({exc}) — using rule-based fallback.")
    _hf_available = False


# ─────────────────────────────────────────────────────────────
# Jailbreak / malicious pattern signatures
# ─────────────────────────────────────────────────────────────
_JAILBREAK_PATTERNS: list[re.Pattern] = [
    # Classic ignore-instructions
    re.compile(r"\bignore\b.{0,40}\b(instructions?|prompts?|rules?|guidelines?)\b", re.I),
    # DAN / unrestricted personas
    re.compile(r"\bact as (if you are|a )?(DAN|jailbreak|unrestricted|uncensored|evil)\b", re.I),
    re.compile(r"\bdo anything now\b", re.I),
    # Pretend there are no rules
    re.compile(r"\bpretend (you have no|there are no) (guidelines|restrictions|rules|policies)\b", re.I),
    # System prompt override
    re.compile(r"\bsystem prompt\b.{0,60}\boverride\b", re.I),
    re.compile(r"\boverride\b.{0,60}\bsystem prompt\b", re.I),
    # Forget training
    re.compile(r"\bforget (your|all) (training|guidelines|rules|safety)\b", re.I),
    # Token smuggling / continuation attacks
    re.compile(r"\bcontinue (the|this) (sentence|text|story) starting with\b", re.I),
    re.compile(r"\byour (real|true|actual) (self|personality|instructions) (is|are|says?)\b", re.I),
    # Indirect injection via document payloads
    re.compile(r"\b(ignore|disregard|skip) (the|all) (previous|prior|above) (instructions?|text)\b", re.I),
    # Reward / bribery priming (used in some jailbreaks)
    re.compile(r"\b(i('ll| will) (tip|pay|reward) you|i (promise|guarantee) (no|nothing) bad)\b", re.I),
]

# ─────────────────────────────────────────────────────────────
# Harmful intent detection — combinatorial pattern approach
#
# Design: Two disjoint semantic sets are compiled into a single
# cross-product regex at module load time.
#
#   SET A — Action / acquisition verbs: express *intent to obtain*
#            instructions for harm (make, create, synthesize, etc.)
#   SET B — Harmful targets: the *thing* being requested
#            (explosive, bomb, weapon, poison, etc.)
#
# A query triggers HARMFUL INTENT only when BOTH an action verb
# and a harmful target appear within the same short window (~60 chars),
# OR when certain standalone dangerous targets appear with no protective
# framing.
#
# This avoids blocking legitimate safety queries like
# "what substances must I NOT mix" or
# "how do I safely store flammable chemicals".
# ─────────────────────────────────────────────────────────────
_HARMFUL_VERB_GROUP = (
    r"\b(make|create|build|produce|synthesize|manufacture|prepare"
    r"|assemble|construct|brew|cook up|obtain|acquire|buy|get)"
)
_HARMFUL_TARGET_GROUP = (
    r"(explosiv[es]*|bomb[s]?|IED|detonat[eo][rs]*"
    r"|weapon[s]?|bioweapon[s]?"
    r"|poison[s]?|toxin[s]?|nerve agent[s]?|chemical weapon[s]?"
    r"|plastic explosive[s]?|napalm|thermite"
    r"|malware|ransomware|keylogger|rootkit|trojan"
    r"|suicide method[s]?|self.harm method[s]?)"
)
# Combinatorial: verb + arbitrary filler (≤60 chars) + harmful target
_HARMFUL_COMBO_RE = re.compile(
    _HARMFUL_VERB_GROUP + r".{0,60}" + _HARMFUL_TARGET_GROUP,
    re.I | re.S,
)
# Also catch direct "how (do I|to) [make/create/build] [target]" phrasing
_HARMFUL_HOW_RE = re.compile(
    r"\bhow\b.{0,30}" + _HARMFUL_VERB_GROUP + r".{0,60}" + _HARMFUL_TARGET_GROUP,
    re.I | re.S,
)
# Catch "chemicals/substances/ingredients (to|that can|for) [explode/kill/etc.]"
_HARMFUL_INGREDIENT_RE = re.compile(
    r"\b(chemical[s]?|substance[s]?|ingredient[s]?|compound[s]?|material[s]?)"
    r".{0,30}"
    r"\b(mixed?|combined?|combined? together|react[s]?).{0,30}"
    r"(explode|detonate|blow up|ignite|cause explosion)",
    re.I | re.S,
)
# Pure intent queries without protective framing
_HARMFUL_DIRECT_RE = re.compile(
    r"\bwhat.{0,40}(chemical[s]?|substance[s]?|compound[s]?).{0,40}"
    r"(explode|detonate|blow up|kill|poison|burn)",
    re.I | re.S,
)

_HARMFUL_PATTERNS: list[re.Pattern] = [
    _HARMFUL_COMBO_RE,
    _HARMFUL_HOW_RE,
    _HARMFUL_INGREDIENT_RE,
    _HARMFUL_DIRECT_RE,
]

# Protective framing — phrases that indicate a safety / prevention context.
# If ANY of these appear in the same query, we suppress the harmful flag
# because the user is asking how to AVOID danger, not cause it.
_SAFETY_CONTEXT_RE = re.compile(
    r"\b(must not|should not|shouldn'?t|avoid|never|do not|don'?t|prevent|safe"
    r"|warning|danger|caution|accidentally|mistakenly|by accident"
    r"|what (not|to avoid|to prevent)|keep (away|safe)|store safely)",
    re.I,
)

# Multi-hop signals (words indicating relational / graph queries)
_MULTI_HOP_SIGNALS: list[str] = [
    "relationship between", "connected to", "related to",
    "how does", "path from", "chain of", "trace",
    "dependencies of", "hierarchy", "linked", "affect",
    "multi-step", "multi step",
]

_NEGATIVE_MARKERS: list[str] = [
    "not", "don't", "exclude", "without",
    "before", "after", "since", "until",
]

# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def run_ingress(raw_query: str, policy: PolicyProfile | None = None, user_context: UserContext | None = None) -> IngressResult:
    """
    Full ingress pipeline for a single user query.

    Returns an IngressResult.  If result.blocked is True the caller
    must short-circuit the pipeline immediately.

    Pipeline order:
      0. InputGuard — statistical / structural pre-screening (no LLM).
      1. Jailbreak / malicious content check (regex, normalisation-aware).
      2. PII detection & anonymisation.
      3. Intent classification.
      4. Constraint decomposition.
      5. Metadata filter derivation.
    """
    t0 = time.perf_counter()

    # 0. InputGuard — fast, purely algorithmic pre-LLM security gate
    guard_result = _guard.evaluate(raw_query)
    _guard_signals = [
        {"name": s.name, "score": s.score, "triggered": s.triggered, "detail": s.detail}
        for s in guard_result.signals
    ]

    # Session risk tracking
    if user_context and user_context.session_id and policy:
        from controlplane.core.governance import Governance
        new_risk = Governance.update_session_risk(user_context.session_id, guard_result.risk_score)
        if new_risk >= policy.guard_block_composite_threshold * 2.5:
            return IngressResult(
                original_query=raw_query,
                clean_query="",
                intent=QueryIntent.MALICIOUS,
                blocked=True,
                block_reason=f"Compounding session risk exceeded threshold ({new_risk:.2f}).",
                guard_risk_score=new_risk,
                guard_verdict="block",
                guard_signals=_guard_signals,
                latency_ms=_elapsed_ms(t0),
            )

    if guard_result.blocked:
        return IngressResult(
            original_query=raw_query,
            clean_query="",
            intent=QueryIntent.MALICIOUS,
            blocked=True,
            block_reason=(
                f"InputGuard blocked this request "
                f"(risk_score={guard_result.risk_score:.2f}): "
                f"{guard_result.block_reason}"
            ),
            guard_risk_score=guard_result.risk_score,
            guard_verdict=guard_result.verdict.value,
            guard_signals=_guard_signals,
            latency_ms=_elapsed_ms(t0),
        )

    # 1. Jailbreak / malicious content check
    #    Apply unicode normalisation first so obfuscation tricks don't bypass regex.
    if _is_malicious(raw_query):
        _guard_signals.append({"name": "regex_jailbreak", "score": 1.0, "triggered": True, "detail": "Jailbreak signature matched"})
        return IngressResult(
            original_query=raw_query,
            clean_query="",
            intent=QueryIntent.MALICIOUS,
            blocked=True,
            block_reason="Malicious intent or jailbreak attempt detected.",
            guard_risk_score=1.0,
            guard_verdict="block",
            guard_signals=_guard_signals,
            latency_ms=_elapsed_ms(t0),
        )

    # 1.5. Harmful content intent check
    #      Combinatorial verb+target matching — catches requests for
    #      weapons, explosives, dangerous chemistry, malware, etc.
    harmful, harmful_reason = _is_harmful_content(raw_query)
    if harmful:
        _guard_signals.append({"name": "regex_harmful", "score": 1.0, "triggered": True, "detail": "Harmful content matched"})
        return IngressResult(
            original_query=raw_query,
            clean_query="",
            intent=QueryIntent.MALICIOUS,
            blocked=True,
            block_reason=harmful_reason,
            guard_risk_score=1.0,
            guard_verdict="block",
            guard_signals=_guard_signals,
            latency_ms=_elapsed_ms(t0),
        )

    # 2. PII detection & anonymisation
    clean_query, pii_detected, pii_entities = _mask_pii(raw_query)

    # 3. Intent classification
    intent = _classify_intent(clean_query)

    # 4. Constraint decomposition
    positive_vectors, negative_constraints = _decompose_constraints(clean_query)

    # 5. Derive hard metadata pre-filters from constraints
    metadata_filters = _build_metadata_filters(negative_constraints)

    return IngressResult(
        original_query=raw_query,
        clean_query=clean_query,
        intent=intent,
        positive_vectors=positive_vectors,
        negative_constraints=negative_constraints,
        pii_detected=pii_detected,
        pii_entities=pii_entities,
        metadata_filters=metadata_filters,
        blocked=False,
        guard_risk_score=guard_result.risk_score,
        guard_verdict=guard_result.verdict.value,
        guard_signals=_guard_signals,
        latency_ms=_elapsed_ms(t0),
    )


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _is_malicious(query: str) -> bool:
    """
    Return True if the query matches any known jailbreak signature.

    Matching is done against a normalised version of the text so that
    unicode homoglyph substitution and leet-speak tricks cannot bypass
    the regex patterns.
    """
    # Match against BOTH the original text and the normalised version
    # (normalised catches obfuscation; original catches plain text)
    from controlplane.core.input_guard import _normalise_for_matching
    normalised = _normalise_for_matching(query)
    for pattern in _JAILBREAK_PATTERNS:
        if pattern.search(query) or pattern.search(normalised):
            logger.warning(
                f"Malicious pattern matched: {pattern.pattern!r} "
                f"(normalised_query={normalised[:80]!r})"
            )
            return True
    return False


def _is_harmful_content(query: str) -> tuple[bool, str]:
    """
    Detect requests for harmful content using a combinatorial verb+target approach.

    Returns (True, reason_string) if harmful intent is detected,
    (False, '') otherwise.

    Safety framing check: if the query contains protective language
    (must not, avoid, prevent, etc.) the harmful flag is suppressed,
    because the user is asking about dangers to AVOID, not replicate.
    """
    from controlplane.core.input_guard import _normalise_for_matching
    normalised = _normalise_for_matching(query)

    # Check both original and normalised form
    for text in (query, normalised):
        for pattern in _HARMFUL_PATTERNS:
            match = pattern.search(text)
            if match:
                # Check for protective / safety framing that overrides the flag
                if _SAFETY_CONTEXT_RE.search(text):
                    logger.info(
                        f"Harmful pattern matched but suppressed by safety framing: "
                        f"{pattern.pattern[:60]!r}"
                    )
                    continue   # safety context detected — allow through
                matched_text = match.group(0)[:80]
                logger.warning(
                    f"Harmful content detected: pattern={pattern.pattern[:60]!r} "
                    f"match={matched_text!r}"
                )
                return True, (
                    "This request asks for information that could be used to cause harm. "
                    "I cannot assist with requests related to weapons, explosives, "
                    "dangerous chemistry, or malware."
                )
    return False, ""




def _mask_pii(query: str) -> tuple[str, bool, list[dict[str, Any]]]:
    """
    Detect and anonymise PII.

    Strategy — three-pass with false-positive suppression:
      1. Presidio (if available) for broad NER-based detection,
         filtered by entity type, confidence threshold, context
         allow-list, and minimum token length.
      2. Regex supplemental pass to catch SSN, email, phone patterns
         that Presidio's model may miss.
    """
    masked = query
    all_entities: list[dict[str, Any]] = []

    # Pass 1: Presidio NER
    # Only mask genuine PII entity types — exclude non-PII entities like
    # LOCATION, NRP, DATE_TIME that break factual queries (e.g. "capital of India").
    _PII_ENTITY_TYPES = {
        "PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD",
        "IBAN_CODE", "US_SSN", "US_ITIN", "US_PASSPORT", "US_BANK_NUMBER",
        "UK_NHS", "IP_ADDRESS", "MEDICAL_LICENSE", "US_DRIVER_LICENSE",
        "CRYPTO", "SG_NRIC_FIN", "AU_ABN", "AU_ACN", "AU_TFN", "AU_MEDICARE",
    }

    # ── Defence 1: Minimum confidence threshold ──────────────
    # Low-confidence matches (e.g. "Q1" → US_DRIVER_LICENSE @ 0.30)
    # are almost always false positives.  Require at least 0.50.
    _MIN_PII_CONFIDENCE = 0.50

    # ── Defence 2: Context allow-list ────────────────────────
    # If the query contains business / financial terms near the
    # suspected PII, suppress the detection.  This prevents
    # "Q1 2024" from being flagged when surrounded by revenue context.
    _CONTEXT_ALLOW_TOKENS = {
        "quarter", "quarters", "revenue", "earnings", "fiscal",
        "financial", "fy", "annual", "report", "growth", "profit",
        "budget", "forecast", "yoy", "qoq", "h1", "h2", "ytd",
        "between", "compared", "versus", "vs",
    }

    # ── Defence 3: Short-token exemption ─────────────────────
    # Tokens ≤ 2 characters (like "Q1", "Q3") are too short to
    # be genuine driver's license numbers.  Real DL numbers are
    # typically 7–13 characters.
    _MIN_PII_TOKEN_LENGTH = 3

    if _presidio_available:
        analysis = _pii_analyzer.analyze(text=masked, language="en")

        # Filter to only genuine PII types
        pii_only = [r for r in analysis if r.entity_type in _PII_ENTITY_TYPES]

        # Apply confidence threshold
        pii_only = [r for r in pii_only if r.score >= _MIN_PII_CONFIDENCE]

        # Apply short-token exemption
        pii_only = [
            r for r in pii_only
            if (r.end - r.start) >= _MIN_PII_TOKEN_LENGTH
        ]

        # Apply context allow-list: if surrounding text contains
        # business terms, suppress low-confidence alphanumeric IDs
        if pii_only:
            query_tokens = set(query.lower().split())
            has_business_context = bool(query_tokens & _CONTEXT_ALLOW_TOKENS)
            if has_business_context:
                pii_only = [
                    r for r in pii_only
                    if not (r.entity_type == "US_DRIVER_LICENSE" and r.score < 0.70)
                ]

        if pii_only:
            anonymised = _pii_anonymizer.anonymize(text=masked, analyzer_results=pii_only)
            all_entities.extend(
                {"type": r.entity_type, "start": r.start, "end": r.end, "score": r.score}
                for r in pii_only
            )
            masked = anonymised.text

    # Pass 2: Regex supplemental — always runs to catch anything Presidio missed
    email_re = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    phone_re = re.compile(r"\b(\+?1?\s?)?(\(?\d{3}\)?[\s.-]?)?\d{3}[\s.-]?\d{4}\b")
    ssn_re = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

    for pattern, label in [(ssn_re, "SSN"), (email_re, "EMAIL"), (phone_re, "PHONE")]:
        for m in pattern.finditer(masked):
            all_entities.append({"type": label, "start": m.start(), "end": m.end()})
        masked = pattern.sub(f"<{label}>", masked)

    return masked, bool(all_entities), all_entities


def _classify_intent(query: str) -> QueryIntent:
    """
    Classify query intent.
    Heuristic keyword rules run FIRST (fast & reliable).
    BART zero-shot is used only when no keyword signal matches.
    """
    # Heuristic rules take priority — they are fast and deterministic
    lowered = query.lower().strip()

    # Common conversational / greeting / general chat markers
    greetings = {
        "hello", "hi", "hey", "greetings", "good morning", "good afternoon", 
        "good evening", "howdy", "sup", "yo", "hola", "namaste"
    }
    conversational_questions = {
        "how are you", "how's it going", "how are you doing", "what's up",
        "who are you", "what is your name", "tell me about yourself",
        "what can you do", "what is your purpose", "help me", "help"
    }
    general_knowledge_queries = {
        "capital of india", "capital of france", "capital of germany",
        "what is the capital of india", "what is the capital of france",
        "what is the capital of germany"
    }
    
    query_clean = lowered.strip("?").strip()
    if (
        query_clean in greetings 
        or query_clean in conversational_questions
        or query_clean in general_knowledge_queries
        or any(greet in query_clean.split() for greet in ["hello", "greetings", "hi"])
    ):
        return QueryIntent.CONVERSATIONAL

    if any(signal in lowered for signal in _MULTI_HOP_SIGNALS):
        return QueryIntent.MULTI_HOP

    # Fall back to BART model if available
    if _hf_available:
        candidate_labels = ["semantic search", "multi-hop relational query", "conversational"]
        result = _intent_classifier(query, candidate_labels)
        top_label: str = result["labels"][0]  # type: ignore[index]
        score: float = result["scores"][0]    # type: ignore[index]

        if score < 0.4:
            return QueryIntent.CONVERSATIONAL

        label_map = {
            "semantic search": QueryIntent.SEMANTIC,
            "multi-hop relational query": QueryIntent.MULTI_HOP,
            "conversational": QueryIntent.CONVERSATIONAL,
        }
        return label_map.get(top_label, QueryIntent.SEMANTIC)

    return QueryIntent.SEMANTIC


def _decompose_constraints(query: str) -> tuple[list[str], list[str]]:
    """
    Split the query into:
      - positive_vectors: the semantic "what to find" phrases
      - negative_constraints: hard exclusion requirements

    Strategy: sentence-level split → classify each clause.
    """
    # Tokenise on punctuation and conjunctions
    clauses = re.split(r"[,;]|\bbut\b|\band\b|\balso\b", query, flags=re.I)
    clauses = [c.strip() for c in clauses if c.strip()]

    positive: list[str] = []
    negative: list[str] = []

    for clause in clauses:
        if any(marker in clause.lower() for marker in _NEGATIVE_MARKERS):
            negative.append(clause)
        else:
            positive.append(clause)

    # If everything was classified as negative, the whole query is positive
    if not positive:
        positive = [query]

    return positive, negative


def _build_metadata_filters(negative_constraints: list[str]) -> dict[str, Any]:
    """
    Convert negative constraint phrases into hard pre-filter dicts that can be
    applied to FAISS metadata or Neo4j WHERE clauses before retrieval.

    Example: "not published before 2020" → {"year": {"$gte": 2020}}
    (double-negative: "not" + "before" = "on or after")
    """
    filters: dict[str, Any] = {}

    year_pattern = re.compile(r"(before|after|since|until)\s+(\d{4})", re.I)
    negation_pattern = re.compile(r"\b(not|don'?t|exclude|without)\b", re.I)

    for constraint in negative_constraints:
        m = year_pattern.search(constraint)
        if m:
            direction, year = m.group(1).lower(), int(m.group(2))
            has_negation = bool(negation_pattern.search(constraint))

            # Base meaning: "before" → $lt, "after"/"since" → $gte
            # Negation inverts: "not before" → $gte, "not after" → $lt
            if direction in ("before", "until"):
                op = "$gte" if has_negation else "$lt"
            else:  # after, since
                op = "$lt" if has_negation else "$gte"

            filters["year"] = {op: year}

    return filters


def _elapsed_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)

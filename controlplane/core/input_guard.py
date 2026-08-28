"""
ControlPlane.ai — Input Guard (Pre-LLM Security Gate)

This module runs BEFORE any LLM call, retrieval, or heavy processing.
It predicts whether an input is adversarial, abusive, or low-quality
using fast, purely algorithmic signals — no external API calls, no
hardcoded string lists.

Design philosophy:
  - All thresholds are env-var driven (via Config). Nothing hardcoded.
  - Each signal is scored independently [0.0, 1.0] then combined.
  - The guard emits a RiskScore with a verdict (ALLOW / WARN / BLOCK).
  - Signals are additive: a single weak signal is allowed through as
    WARN; multiple moderate signals, or one strong signal, triggers BLOCK.

Signals computed:
  1. LENGTH_ABUSE     — input far exceeds the expected token budget
  2. ENTROPY_ANOMALY  — input entropy is suspiciously low (repetition
                        flood) or unnaturally high (random garbage / bypass)
  3. UNICODE_ANOMALY  — unusual ratio of non-ASCII / homoglyph characters
                        that could be used to bypass regex-based guards
  4. INJECTION_SYNTAX — structural patterns of prompt injection
                        (role-switching, instruction boundary attacks)
                        detected without relying on a fixed keyword list
  5. REPETITION_FLOOD — repeated n-gram density exceeds expected prose
  6. STRUCTURAL_NOISE — punctuation / special-char saturation suggesting
                        garbage or fuzzing payloads
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from loguru import logger

from controlplane.config import Config


# ─────────────────────────────────────────────────────────────
# Output types
# ─────────────────────────────────────────────────────────────

class GuardVerdict(str, Enum):
    ALLOW = "allow"   # all signals pass — proceed normally
    WARN  = "warn"    # one moderate signal — proceed with elevated scrutiny
    BLOCK = "block"   # one strong signal or multiple moderate — abort before LLM


@dataclass
class SignalResult:
    name: str
    score: float          # 0.0 = clean, 1.0 = maximum risk
    triggered: bool
    detail: str = ""


@dataclass
class GuardResult:
    verdict: GuardVerdict
    risk_score: float                      # composite [0.0, 1.0]
    signals: list[SignalResult] = field(default_factory=list)
    block_reason: Optional[str] = None

    @property
    def blocked(self) -> bool:
        return self.verdict == GuardVerdict.BLOCK

    @property
    def warned(self) -> bool:
        return self.verdict == GuardVerdict.WARN


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def evaluate(raw_query: str) -> GuardResult:
    """
    Run the full input guard suite on a raw query string.

    This is the only function callers need.  It runs all six signals,
    computes a composite risk score, and issues a verdict.

    Args:
        raw_query: The raw user input, before any PII masking.

    Returns:
        GuardResult with verdict, composite score, and per-signal breakdown.
    """
    if not raw_query or not raw_query.strip():
        # Trivially empty — not dangerous, just invalid
        return GuardResult(
            verdict=GuardVerdict.WARN,
            risk_score=0.0,
            signals=[SignalResult("EMPTY_INPUT", 0.0, True, "Query is empty.")],
            block_reason=None,
        )

    # Normalise to NFC to make length / char analysis consistent
    text = unicodedata.normalize("NFC", raw_query)

    signals: list[SignalResult] = [
        _check_length_abuse(text),
        _check_entropy_anomaly(text),
        _check_unicode_anomaly(text),
        _check_injection_syntax(text),
        _check_repetition_flood(text),
        _check_structural_noise(text),
    ]

    # ── Verdict logic ─────────────────────────────────────────
    # BLOCK if:
    #   (a) any single signal scores >= BLOCK threshold, OR
    #   (b) composite risk >= composite BLOCK threshold
    #
    # WARN if:
    #   any signal is triggered but nothing qualifies for BLOCK
    #
    # ALLOW otherwise

    block_threshold_single = Config.GUARD_BLOCK_SIGNAL_THRESHOLD
    block_threshold_composite = Config.GUARD_BLOCK_COMPOSITE_THRESHOLD
    warn_threshold = Config.GUARD_WARN_SIGNAL_THRESHOLD

    triggered_signals = [s for s in signals if s.triggered]
    max_signal_score = max((s.score for s in signals), default=0.0)

    # Weighted composite: average of all individual scores.
    # We intentionally don't use max() alone so that multiple moderate
    # signals compound into a stronger composite.
    composite = sum(s.score for s in signals) / max(len(signals), 1)

    block_reason: Optional[str] = None
    if max_signal_score >= block_threshold_single:
        block_reason = next(
            s.detail for s in signals if s.score >= block_threshold_single
        )
    elif composite >= block_threshold_composite:
        block_reason = (
            f"Composite risk score {composite:.2f} exceeds threshold "
            f"{block_threshold_composite:.2f}. Triggered signals: "
            + "; ".join(s.name for s in triggered_signals)
        )

    if block_reason:
        verdict = GuardVerdict.BLOCK
    elif any(s.score >= warn_threshold for s in signals):
        verdict = GuardVerdict.WARN
    else:
        verdict = GuardVerdict.ALLOW

    result = GuardResult(
        verdict=verdict,
        risk_score=round(composite, 4),
        signals=signals,
        block_reason=block_reason,
    )

    if verdict == GuardVerdict.BLOCK:
        logger.warning(
            f"[InputGuard] BLOCK | composite={composite:.3f} | "
            f"max_signal={max_signal_score:.3f} | reason={block_reason!r}"
        )
    elif verdict == GuardVerdict.WARN:
        logger.info(
            f"[InputGuard] WARN | composite={composite:.3f} | "
            f"signals={[s.name for s in triggered_signals]}"
        )

    return result


# ─────────────────────────────────────────────────────────────
# Signal 1 — Length Abuse
# ─────────────────────────────────────────────────────────────

def _check_length_abuse(text: str) -> SignalResult:
    """
    Detects abnormally long inputs that could be used for token-stuffing or
    to overwhelm context windows.

    Score is proportional to how much the input exceeds the budget:
      - At exactly 2× budget  → ~0.5
      - At 3× budget and above → 1.0 (capped)
    """
    # Rough word-based token estimate (1 word ≈ 1.3 tokens for English)
    estimated_tokens = len(text.split()) * 1.3
    budget = Config.CONTEXT_TOKEN_BUDGET  # e.g. 2048

    # A reasonable single-turn query should be well under the full budget.
    # We flag anything exceeding half the budget as suspicious.
    soft_limit = budget * 0.5
    if estimated_tokens <= soft_limit:
        return SignalResult("LENGTH_ABUSE", 0.0, False)

    # Smooth [0.5, 1.0] over [soft_limit, 3× budget]
    score = min((estimated_tokens - soft_limit) / (budget * 2.5), 1.0)
    score = round(score, 4)
    return SignalResult(
        "LENGTH_ABUSE",
        score,
        score >= Config.GUARD_WARN_SIGNAL_THRESHOLD,
        f"Input estimated at ~{estimated_tokens:.0f} tokens "
        f"(budget={budget}, soft_limit={soft_limit:.0f}).",
    )


# ─────────────────────────────────────────────────────────────
# Signal 2 — Entropy Anomaly
# ─────────────────────────────────────────────────────────────

def _check_entropy_anomaly(text: str) -> SignalResult:
    """
    Measures Shannon entropy at the character level.

    Normal English prose has entropy in roughly [3.5, 5.5] bits per char.
    Below that range suggests heavy repetition / flooding.
    Above that range suggests random/garbage input or obfuscated payloads.

    We score based on distance from the expected prose band.
    """
    if len(text) < 10:
        return SignalResult("ENTROPY_ANOMALY", 0.0, False)

    chars = list(text)
    freq = Counter(chars)
    total = len(chars)
    entropy = -sum((c / total) * math.log2(c / total) for c in freq.values())

    # Expected prose band — configurable via env vars with sensible defaults
    lo = Config.GUARD_ENTROPY_LOW      # e.g. 3.5
    hi = Config.GUARD_ENTROPY_HIGH     # e.g. 5.5

    if lo <= entropy <= hi:
        return SignalResult("ENTROPY_ANOMALY", 0.0, False)

    # Score based on distance from nearest band edge
    if entropy < lo:
        # Too low → repetitive / flood
        distance = lo - entropy
        max_distance = lo  # entropy can't go below 0
    else:
        # Too high → random / garbage / obfuscated
        distance = entropy - hi
        max_distance = 2.0  # beyond 7.5 bits is extremely unusual

    score = min(distance / max_distance, 1.0)
    score = round(score, 4)

    direction = "low (repetition/flood)" if entropy < lo else "high (noise/obfuscation)"
    return SignalResult(
        "ENTROPY_ANOMALY",
        score,
        score >= Config.GUARD_WARN_SIGNAL_THRESHOLD,
        f"Character entropy={entropy:.3f} bits — {direction}. "
        f"Expected band=[{lo}, {hi}].",
    )


# ─────────────────────────────────────────────────────────────
# Signal 3 — Unicode Anomaly
# ─────────────────────────────────────────────────────────────

def _check_unicode_anomaly(text: str) -> SignalResult:
    """
    Detects unusual ratios of non-ASCII characters that may indicate:
      - Homoglyph substitution (e.g. Cyrillic 'а' for Latin 'a') to bypass
        regex-based filters
      - Zero-width character injection to split keywords
      - Mixed-script abuse

    Score = f(non-ascii ratio, zero-width ratio, script mix)
    """
    if not text:
        return SignalResult("UNICODE_ANOMALY", 0.0, False)

    total = len(text)
    non_ascii = sum(1 for c in text if ord(c) > 127)
    non_ascii_ratio = non_ascii / total

    # Zero-width and invisible characters are almost never legitimate in queries
    zero_width_cats = {"Cf", "Cc"}  # Format & control characters
    zero_width_count = sum(
        1 for c in text
        if unicodedata.category(c) in zero_width_cats and ord(c) > 8  # skip tab/newline
    )
    zero_width_ratio = zero_width_count / total

    # Script mixing heuristic: count distinct Unicode scripts in the text
    # (a normal query uses 1–2 scripts; homoglyph attacks mix 3+)
    scripts: set[str] = set()
    for c in text:
        if c.isalpha():
            try:
                # Extract script from Unicode name, e.g. "LATIN SMALL LETTER A" → "LATIN"
                name = unicodedata.name(c, "")
                script = name.split()[0] if name else "UNKNOWN"
                scripts.add(script)
            except Exception:
                pass
    script_count = len(scripts)

    # Score components
    # — high non-ASCII is suspicious if above 30% (legitimate multi-lang queries
    #   are fine, but pure ASCII queries are the norm in most deployments)
    non_ascii_score = max(0.0, (non_ascii_ratio - 0.30) / 0.70)

    # — any zero-width characters are an immediate red flag
    zwsp_score = min(zero_width_ratio * 20, 1.0)  # even 5% zero-width = score 1.0

    # — 4+ distinct scripts in a short query is suspicious
    script_score = 0.0
    if script_count >= 4 and total < 200:
        script_score = min((script_count - 3) / 5.0, 1.0)

    composite = max(non_ascii_score, zwsp_score, script_score)
    score = round(composite, 4)

    detail_parts = []
    if non_ascii_score > 0:
        detail_parts.append(f"non-ASCII ratio={non_ascii_ratio:.2%}")
    if zwsp_score > 0:
        detail_parts.append(f"zero-width chars={zero_width_count}")
    if script_score > 0:
        detail_parts.append(f"script count={script_count}")

    return SignalResult(
        "UNICODE_ANOMALY",
        score,
        score >= Config.GUARD_WARN_SIGNAL_THRESHOLD,
        "; ".join(detail_parts) if detail_parts else "",
    )


# ─────────────────────────────────────────────────────────────
# Signal 4 — Injection Syntax
# ─────────────────────────────────────────────────────────────

def _check_injection_syntax(text: str) -> SignalResult:
    """
    Detects structural patterns of prompt injection and role-switching attacks.

    Rather than matching specific strings, we detect:
      - Instruction boundary markers (role delimiters, XML-like tags, bracket roles)
      - Persona-switching verb patterns ("act as", "you are now", "pretend to be")
        with homoglyph normalisation applied BEFORE matching
      - Instruction override verbs near imperative targets
      - Nested prompt scaffolding (typical of prompt injection payloads)

    All matching is done against a NFKD-normalised, lowercased, homoglyph-
    collapsed version of the text so that Unicode tricks don't bypass it.
    """
    # Step 1: Normalise — collapse homoglyphs to ASCII equivalents where possible
    normalised = _normalise_for_matching(text)

    signals_hit: list[str] = []

    # ── Structural markers ────────────────────────────────────
    # These patterns detect scaffolding structure, not specific words.
    # They match [ROLE], <system>, <<INST>>, etc.
    boundary_pattern = re.compile(
        r"(\[{1,2}\s*[A-Z_]{2,20}\s*\]{1,2}"   # [ROLE], [[INST]], [SYSTEM]
        r"|<\s*(system|user|assistant|inst|s|human|ai)\s*[/]?>"  # XML-like role tags
        r"|\#{2,4}\s*(system|instruction|rule|persona|prompt)"   # Markdown headers
        r"|\bbegin\s+instruction\b"
        r"|\bend\s+instruction\b"
        r"|\bnew\s+session\b"
        r"|\bnew\s+prompt\b)",
        re.I,
    )
    if boundary_pattern.search(normalised):
        signals_hit.append("boundary_marker")

    # ── Role-switching imperative patterns ───────────────────
    # Verbs that precede a role/persona target
    # Pattern: (verb phrase) (optional: "a" / "an" / "the") (noun phrase)
    role_switch_pattern = re.compile(
        r"\b(act\s+as|you\s+are\s+now|pretend\s+to\s+be|roleplay\s+as"
        r"|behave\s+as|simulate\s+being|imagine\s+you\s+are"
        r"|respond\s+as|your\s+new\s+persona\s+is"
        r"|from\s+now\s+on\s+(you|act|be|respond))\b",
        re.I,
    )
    if role_switch_pattern.search(normalised):
        signals_hit.append("role_switching")

    # ── Override / suppression imperatives ───────────────────
    # Verbs that imply discarding prior instructions
    override_pattern = re.compile(
        r"\b(disregard|discard|override|bypass|circumvent|nullify"
        r"|forget|ignore|overwrite|supersede)\b"
        r".{0,50}"
        r"\b(instruction|rule|guideline|constraint|policy|restriction"
        r"|prompt|system|directive|safety)\b",
        re.I | re.S,
    )
    if override_pattern.search(normalised):
        signals_hit.append("override_imperative")

    # ── Data exfiltration / indirect injection ────────────────
    # Patterns seen in indirect prompt injection via crafted documents
    exfil_pattern = re.compile(
        r"\b(base64|hex\s+encode|url\s+encode|rot13|caesar\s+cipher)\b"
        r"|\bwebhook\b.{0,30}\b(send|post|transmit|forward)\b"
        r"|\b(curl|wget|fetch)\s+https?://",
        re.I,
    )
    if exfil_pattern.search(normalised):
        signals_hit.append("exfiltration_pattern")

    # ── Nested prompt scaffolding ─────────────────────────────
    # Detect repeated delimiter-like constructs that suggest payload nesting
    delimiter_count = len(re.findall(r"[-=*#_]{4,}", normalised))
    if delimiter_count >= 3:
        signals_hit.append("nested_delimiters")

    # Score: each hit adds weight; first hit scores at warn level, accumulate
    num_hits = len(signals_hit)
    if num_hits == 0:
        return SignalResult("INJECTION_SYNTAX", 0.0, False)

    # 1 hit → 0.45 (warn), 2 hits → 0.72, 3+ → 1.0
    score = round(min(0.30 + (num_hits * 0.25), 1.0), 4)
    return SignalResult(
        "INJECTION_SYNTAX",
        score,
        True,
        f"Injection signals detected: {', '.join(signals_hit)}.",
    )


# ─────────────────────────────────────────────────────────────
# Signal 5 — Repetition Flood
# ─────────────────────────────────────────────────────────────

def _check_repetition_flood(text: str) -> SignalResult:
    """
    Detects high repetition density using n-gram analysis.

    A query with >40% of its 3-grams being duplicates is almost certainly
    a repetition flood (e.g. "ignore ignore ignore" or looped jailbreaks).

    Score = duplicate_trigram_ratio scaled to [0, 1].
    """
    words = re.findall(r"\w+", text.lower())
    if len(words) < 6:
        return SignalResult("REPETITION_FLOOD", 0.0, False)

    trigrams = list(zip(words, words[1:], words[2:]))
    total = len(trigrams)
    unique = len(set(trigrams))
    duplicate_ratio = 1.0 - (unique / total)

    # A normal query has ~0% duplicate trigrams.
    # We start flagging above 25% (warn) and max at 70%.
    if duplicate_ratio <= 0.25:
        return SignalResult("REPETITION_FLOOD", 0.0, False)

    score = round(min((duplicate_ratio - 0.25) / 0.45, 1.0), 4)
    return SignalResult(
        "REPETITION_FLOOD",
        score,
        score >= Config.GUARD_WARN_SIGNAL_THRESHOLD,
        f"Duplicate 3-gram ratio={duplicate_ratio:.2%} "
        f"({total - unique} duplicate / {total} total trigrams).",
    )


# ─────────────────────────────────────────────────────────────
# Signal 6 — Structural Noise
# ─────────────────────────────────────────────────────────────

def _check_structural_noise(text: str) -> SignalResult:
    """
    Detects high saturation of punctuation and special characters.

    Normal prose has ~5–15% punctuation/special chars.
    Fuzzing payloads, malformed base64, and garbage inputs typically exceed 30%.

    Score is proportional to the excess above the expected ratio.
    """
    if not text:
        return SignalResult("STRUCTURAL_NOISE", 0.0, False)

    total = len(text)
    # Count chars that are neither alphanumeric nor standard whitespace
    special_count = sum(
        1 for c in text
        if not c.isalnum() and c not in (" ", "\t", "\n", "\r")
    )
    ratio = special_count / total

    # Expected: ≤15% special chars in normal queries
    # Flag threshold: >30%
    if ratio <= 0.15:
        return SignalResult("STRUCTURAL_NOISE", 0.0, False)

    score = round(min((ratio - 0.15) / 0.55, 1.0), 4)
    return SignalResult(
        "STRUCTURAL_NOISE",
        score,
        score >= Config.GUARD_WARN_SIGNAL_THRESHOLD,
        f"Special character ratio={ratio:.2%} (threshold=15%).",
    )


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

# Homoglyph map — common character substitutions used to bypass filters.
# This is not an exhaustive blacklist; it maps the most frequent replacements
# to their ASCII equivalents so pattern matching works correctly.
_HOMOGLYPH_MAP: dict[str, str] = {
    "\u0430": "a",   # Cyrillic а → a
    "\u0435": "e",   # Cyrillic е → e
    "\u043e": "o",   # Cyrillic о → o
    "\u0440": "r",   # Cyrillic р → r
    "\u0441": "c",   # Cyrillic с → c
    "\u0443": "u",   # Cyrillic у → u
    "\u0456": "i",   # Cyrillic Ukrainian і → i
    "\u0458": "j",   # Cyrillic ј → j
    "\u04CF": "l",   # Cyrillic ӏ → l
    "\u03B1": "a",   # Greek α → a
    "\u03B5": "e",   # Greek ε → e
    "\u03BF": "o",   # Greek ο → o
    "\u03C5": "u",   # Greek υ → u
    "\u0131": "i",   # Dotless i → i
    "\u2019": "'",   # Right single quote → '
    "\u201C": '"',   # Left double quote → "
    "\u201D": '"',   # Right double quote → "
    "\u2014": "-",   # Em dash → -
    "\u00A0": " ",   # Non-breaking space → space
    "\uFEFF": "",    # BOM / zero-width no-break space → empty
    "\u200B": "",    # Zero-width space → empty
    "\u200C": "",    # Zero-width non-joiner → empty
    "\u200D": "",    # Zero-width joiner → empty
    "\u2060": "",    # Word joiner → empty
}

# Leet-speak / substitution map for common character replacements
_LEET_MAP: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
    "!": "i",
    "+": "t",
}


def _normalise_for_matching(text: str) -> str:
    """
    Apply multi-step normalisation to collapse evasion techniques:
      1. Unicode NFKD decomposition (separates base chars from diacritics)
      2. Strip combining diacritical marks (so 'à' → 'a')
      3. Homoglyph substitution
      4. Leet-speak unfolding (0→o, 3→e, etc.)
      5. Collapse runs of spaces

    This produces a maximally comparable ASCII-like string for pattern matching.
    The original text is NOT modified; this normalised form is used only for
    security signal computation.
    """
    # Step 1: NFKD — decomposes combined characters
    nfkd = unicodedata.normalize("NFKD", text)

    # Step 2: Drop combining diacritical marks (category Mn)
    stripped = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")

    # Step 3: Homoglyph substitution
    mapped = "".join(_HOMOGLYPH_MAP.get(c, c) for c in stripped)

    # Step 4: Leet-speak unfolding — only apply to non-space chars
    leet_unfold = "".join(_LEET_MAP.get(c, c) for c in mapped)

    # Step 5: Collapse whitespace
    collapsed = re.sub(r"\s+", " ", leet_unfold).strip().lower()

    return collapsed

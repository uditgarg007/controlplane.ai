# ControlPlane.ai — How It Works

## What Is ControlPlane.ai?

ControlPlane.ai is a **production-grade AI middleware** that sits between your users and a Large Language Model (Gemini). Instead of letting raw queries hit an LLM directly, ControlPlane wraps every request in a **four-stage pipeline** with built-in safety, validation, caching, and self-repair — making the system reliable, observable, and grounded.

---

## Pipeline Architecture

Every user query flows through these stages in sequence:

```
User Query
    │
    ▼
┌──────────────────────────────────────────┐
│  Governance & Policy Engine              │
│  • Dynamically maps UserContext to       │
│    a PolicyProfile (thresholds)          │
│  • Self-adjusts via Active Feedback Loops│
└────────────────┬─────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│  Stage 0: Semantic Cache Check           │
│  • Exact hash match via Redis            │
│  • Fuzzy match via in-process vectors    │
│  • If HIT → return instantly, 100% saved │
└────────────────┬─────────────────────────┘
                 │ cache miss
                 ▼
┌──────────────────────────────────────────┐
│  Stage 1: Ingress & Decomposer          │
│  • Multi-turn Session Risk tracking     │
│  • Jailbreak / malicious prompt filter  │
│  • PII Masking (Presidio + regex)       │
│  • Intent Classification (BART + rules) │
│  • Constraint Decomposition             │
└────────────────┬─────────────────────────┘
                 │ clean_query + intent + constraints
                 ▼
┌──────────────────────────────────────────┐
│  Stage 2: Retrieval Routing              │
│  • SEMANTIC → FAISS vector search       │
│  • MULTI_HOP → Neo4j graph traversal    │
│  • Context compression (LLMLingua)      │
│  • Mock chunks (fallback if no index)   │
└────────────────┬─────────────────────────┘
                 │ compressed_context
                 ▼
┌──────────────────────────────────────────┐
│  Stage 3: Generation & In-Flight Valid.  │
│  • Pre-generation grounding (AlignScore) │
│  • LLM call (Gemini via OpenAI compat)   │
│  • Format validation (schema checks)     │
│  • Severity routing: PASS / WARN / FAIL  │
└────────────────┬─────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
     PASS/WARN          FAIL
        │                 │
        │                 ▼
        │    ┌────────────────────────────┐
        │    │  Stage 4: Repair Loop      │
        │    │  • CRAG/Self-RAG judge     │
        │    │  • Query rewriting         │
        │    │  • Channel switching       │
        │    │    (vector → graph → web)  │
        │    │  • Bounded iteration (≤3)  │
        │    └───────────┬────────────────┘
        │                │
        └────────┬───────┘
                 ▼
┌──────────────────────────────────────────┐
│  Stage 5: HITL Quarantine                │
│  • Flagged queries go to hitl_queue      │
└────────────────┬─────────────────────────┘
                 ▼
┌──────────────────────────────────────────┐
│  Parallel Observability Layer            │
│  • AI-as-Judge Bias Audit (Async)       │
│  • Metrics dashboard (live)             │
│  • Token economics tracking             │
│  • Audit Logs (SQLite)                  │
└────────────────┬─────────────────────────┘
                 ▼
           Final Response
```

---

## Stage-by-Stage Deep Dive

### Stage 0 — Semantic Cache

**File:** `controlplane/cache/semantic_cache.py`

Before any computation, the cache is checked:

1. **Exact match** — the query is hashed (SHA-256 after normalisation) and looked up in Redis.
2. **Semantic match** — the query is embedded using `sentence-transformers/all-MiniLM-L6-v2` and compared against an in-process vector cache. If cosine similarity ≥ 0.92, the cached answer is served.
3. **Cache miss** — the full pipeline runs. After completion, the result is stored in both Redis and the vector cache.

This eliminates duplicate LLM calls for repeated or paraphrased questions.

---

### Stage 1 — Ingress & Decomposer

**File:** `controlplane/core/ingress.py`

The ingress stage is the safety gatekeeper. It performs four operations:

| Step | What It Does | How |
|------|-------------|-----|
| **Jailbreak Detection** | Blocks adversarial prompts ("Ignore all instructions…", "Act as DAN…") | Keyword matching against known attack patterns |
| **PII Masking** | Strips personally identifiable information before it reaches the LLM | Presidio NER (emails, phones, SSNs, credit cards, person names) + regex fallback |
| **Intent Classification** | Determines query type: `SEMANTIC`, `MULTI_HOP`, `CONVERSATIONAL`, or `MALICIOUS` | Heuristic rules first (fast, deterministic), then BART zero-shot classification as fallback |
| **Constraint Decomposition** | Splits complex queries into positive search vectors and negative exclusion constraints | Regex splitting on conjunctions, negation markers ("but not", "exclude") |

If a query is classified as `MALICIOUS`, the pipeline stops immediately and returns a blocked response.

---

### Stage 2 — Retrieval Routing

**File:** `controlplane/core/retrieval.py`

Based on the intent from Stage 1, retrieval is routed to the appropriate backend:

- **`SEMANTIC`** → FAISS vector index (local) for similarity search. The system comes pre-configured with a live FAISS index managed via `scripts/build_index.py`, stored in `./data/faiss.index`.
- **`MULTI_HOP`** → Neo4j graph database for relational traversal
- **`CONVERSATIONAL`** → Bypassed (query goes directly to LLM with a relaxed prompt)

After retrieval, the raw chunks are compressed using LLMLingua (if available) or hard-truncated to fit the configured token budget (default: 2048 tokens). Compression ratios and token counts are tracked for observability.

If the FAISS index is missing or empty, the system returns **mock chunks** (prefixed with `[MOCK]`) as a graceful fallback.

---

### Stage 3 — Generation & In-Flight Validation

**File:** `controlplane/core/generation.py`

This is the core LLM interaction stage. It performs:

1. **Pre-generation Grounding (AlignScore)** — Compares the *user's query* against the retrieved context *before* generation. If the query cannot be grounded in the context (and isn't conversational), the pipeline short-circuits with a `FAIL` severity, saving LLM tokens and time. It runs locally using `AlignScore-base.ckpt` with a batch size of 16.

2. **Prompt Construction** — For grounded queries, the LLM receives a strict system prompt ("Answer ONLY using the provided context"). For conversational queries (greetings, general knowledge, mock context), a relaxed prompt is used instead.

3. **LLM Call** — Calls the Gemini API via the OpenAI-compatible endpoint. Powered by **Tenacity for exponential backoff** to automatically retry transient quota issues, and a **multi-model fallback** mechanism: if a model exhausts its retries due to a hard rate limit (429), the system seamlessly fails over to alternative models (`gemini-3.5-flash-lite` → `gemini-3.5-flash` → `gemini-flash-latest`).

4. **Format Validation** — Checks if the output meets expected constraints:
   - Non-empty, non-whitespace
   - Minimum length (10 characters)
   - No sycophantic prefixes ("Absolutely!", "Great question!")
   - JSON schema validation (if a schema is provided)

5. **Severity Routing** — Based on the validation results:
   - `PASS` — output is clean, grounded, well-formatted
   - `WARN` — borderline alignment score; output served with caution
   - `FAIL` — format invalid OR hallucination detected; triggers the repair loop

---

### Stage 4 — Corrective Repair Loop

**File:** `controlplane/core/repair.py`

When generation severity is `FAIL`, the repair loop kicks in (up to 3 iterations):

1. **Judge** — Diagnoses WHY the generation failed (hallucination? empty output? format error?)
2. **Query Rewriter** — Rewrites the original query using different strategies (broadening, synonym expansion, constraint relaxation)
3. **Channel Switching** — Rotates through retrieval backends:
   - Iteration 1: switch to `graph` (Neo4j)
   - Iteration 2: switch to `web` (web search fallback)
   - Iteration 3: fall back to `vector` (retry FAISS)
4. **Re-generation** — Runs through Stage 2 + 3 again with the rewritten query
5. **Early exit** — If the new output achieves `PASS`, the loop stops immediately

The repair loop has a hard cap to prevent runaway API cost.

---

### Stage 5 — HITL Quarantine & Governance

**File:** `controlplane/core/governance.py`

Before the final response is delivered, the system evaluates the final severity. If it evaluates to `QUARANTINE` (for instance, a borderline response under a `strict_external` policy), the response is intercepted.
- A polite `[QUARANTINED]` message is sent to the user.
- The original query and raw LLM output are stored in `hitl_queue` in the local SQLite database.
- All blocks and quarantines are recorded in the `audit_logs` table for compliance.

---

### Observability Layer

**Files:** `controlplane/observability/metrics.py`, `controlplane/observability/bias_monitor.py`

Runs in **parallel** with the main pipeline (zero latency impact):

- **Metrics Dashboard** — Tracks total requests, severity distribution, latency, cache hit rate, alignment scores, token compression ratios, and repair statistics. Served at `/metrics/dashboard`.
- **Bias Monitor** — Asynchronously audits LLM outputs using IBM AIF360 for disparate impact and statistical parity, plus a keyword-based stereotype detector. Results surfaced at `/metrics/bias`.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Server | FastAPI + Uvicorn |
| LLM Backend | Google Gemini (via OpenAI compatibility layer) |
| Intent Classification | BART zero-shot (`facebook/bart-large-mnli`) + heuristic rules |
| PII Detection | Microsoft Presidio + regex |
| Vector Search | FAISS + sentence-transformers (`all-MiniLM-L6-v2`) |
| Graph Database | Neo4j Aura |
| Context Compression | LLMLingua |
| Hallucination Detection | AlignScore (NLI) / Jaccard overlap fallback |
| Bias Monitoring | IBM AIF360 |
| Caching | Redis (exact) + in-process vector cache (semantic) |
| Dashboard | Vanilla HTML/CSS/JS with Canvas charts |

---

## Issues We Faced & How We Resolved Them

### Issue 1: "Insufficient context to answer" on ALL queries

**Symptom:** Every query — including greetings ("hello") and factual questions ("capital of India") — returned `"Insufficient context to answer."` despite the Gemini API dashboard showing successful API calls.

**Root Cause:** The system prompt strictly instructed the LLM: *"Answer ONLY using the provided context. If the context is insufficient, respond: 'Insufficient context to answer.'"* Since no FAISS index was loaded, every query received mock context that didn't contain real answers. The LLM correctly followed its instructions and refused to answer.

**Fix:** Implemented a **dynamic prompting system** in `generation.py`:
- Queries classified as `CONVERSATIONAL`, or queries where the context contains only mock chunks (`[MOCK]`), or queries with empty context → switch to a relaxed system prompt that allows the LLM to answer freely.
- All other queries (with real retrieved context) continue to use the strict grounding prompt.
- Hallucination grounding checks are bypassed for conversational queries since there is no context to ground against.

---

### Issue 2: Presidio masking geographic entities as PII

**Symptom:** "What is the capital of India" was being transformed into `"what is capital of <LOCATION>"` before reaching the LLM, destroying the factual query.

**Root Cause:** Presidio's NER engine detected "India" as a `LOCATION` entity and anonymised it. This is correct behaviour for PII protection, but `LOCATION` is not personally identifiable information.

**Fix:** Added a whitelist of genuine PII entity types in `ingress.py` (`PERSON`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `CREDIT_CARD`, `US_SSN`, etc.). Non-PII entities like `LOCATION`, `NRP` (nationality), and `DATE_TIME` are now excluded from masking.

---

### Issue 3: `[MOCK]` detection failing due to tokeniser spacing

**Symptom:** Even after fixing Issue 1, the mock context detection check `"[MOCK]" in compressed_context` was returning `False`, causing queries to still go through the strict grounding path.

**Root Cause:** The sentence-transformers tokeniser inserts spaces around special characters during compression. The mock chunk `"[MOCK] Context chunk for: query"` was being transformed to `"[ MOCK ] Context chunk for : query"`. The simple string check for `"[MOCK]"` failed against `"[ MOCK ]"`.

**Fix:** Replaced the string check with a regex pattern `re.search(r"\[\s*MOCK\s*\]", ctx)` that handles both the original and space-padded variants.

---

### Issue 4: Severity router tests failing (WARN instead of FAIL)

**Symptom:** Two unit tests — `test_fail_on_hallucination` and `test_fail_on_format_error` — were asserting `SeverityLevel.FAIL` but receiving `SeverityLevel.WARN`.

**Root Cause:** The `_route_severity` function was configured to only return `FAIL` when **both** format errors AND hallucination flags were present simultaneously (`if not format_valid and hallucination_flags`). Individual issues were demoted to `WARN`.

**Fix:** Changed the logic to return `FAIL` if **either** condition is present (`if not format_valid or hallucination_flags`). This matches the expected behaviour: any format error or any hallucination flag should trigger the repair loop.

---

### Issue 5: Gemini API 429 Rate Limit / Quota Exceeded

**Symptom:** After ~20 requests, all queries returned `[LLM ERROR] Error code: 429 - Quota exceeded for metric: generate_content_free_tier_requests, limit: 20, model: gemini-2.5-flash`.

**Root Cause:** `gemini-2.5-flash` on the Gemini Free Tier allows only **20 requests per day**. This low quota was exhausted quickly during development and testing.

**Fix (two-part):**
1. **Switched default model** to `gemini-3.5-flash-lite`, which has a significantly higher free-tier quota (1,500 requests/day, 15 RPM).
2. **Added automatic multi-model fallback** in `_call_llm`: if any model returns a 429 or `RESOURCE_EXHAUSTED` error, the system automatically tries the next candidate model (`gemini-3.5-flash-lite` → `gemini-3.5-flash` → `gemini-flash-latest`) before giving up.

---

### Issue 6: OpenAI → Gemini migration errors

**Symptom:** Various import errors and API incompatibilities when switching from the OpenAI backend to Gemini.

**Root Cause:** The codebase was originally built for the OpenAI API. Migrating to Gemini required updating environment variable names, API base URLs, and model identifiers.

**Fix:** Updated `config.py` and `generation.py` to use `GEMINI_API_KEY`, `GEMINI_MODEL`, and `GEMINI_MAX_TOKENS`, pointing the OpenAI client to Gemini's OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`).

---

### Issue 7: Presidio masking financial quarters as US Driver's Licenses

**Symptom:** Queries containing financial quarters (e.g., "Revenue grew 15% between Q1 2024 and Q3 2025") were incorrectly triggering the PII blocker, replacing the quarters with `<US_DRIVER_LICENSE>`.

**Root Cause:** Several U.S. states format their driver's license numbers as a single letter followed by digits. Presidio's NER engine evaluated short tokens like "Q1" and "Q3" as driver's licenses (albeit with low confidence scores around 0.3) and aggressively masked them.

**Fix:** Implemented a three-layer false-positive suppression strategy in `ingress.py`:
1. **Confidence Threshold:** Enforced a minimum confidence score of 0.5 for PII detections.
2. **Context Allow-List:** Allowed low-confidence alphanumeric IDs to pass if the surrounding text contained business or financial terms (e.g., "quarter", "revenue", "fiscal").
3. **Short-Token Exemption:** Ignored PII matches that were fewer than 3 characters long (e.g., "Q1").

This Edge Case highlights our safety layer's precision and demonstrates a robust approach to mitigating false positives in real-world enterprise AI deployments.

---

### Issue 8: "Insufficient context" on Web Queries (duckduckgo_search timeout)

**Symptom:** Queries requiring web search (e.g., "what is best 2026 indie game") triggered the web retrieval repair loop but still failed with "Insufficient context to answer".

**Root Cause:** The `duckduckgo_search` library was silently timing out due to upstream API changes at DuckDuckGo, returning 0 results instead of raising an error. The LLM correctly identified 0 results as insufficient context.

**Fix:** Uninstalled the deprecated `duckduckgo_search` and migrated to the officially maintained `ddgs` library. Updated `web_search.py` imports, fully restoring live web retrieval.

---

### Issue 9: AlignScore Installation Dependency Conflicts

**Symptom:** `pip install alignscore` failed on Python 3.11+ due to archaic, strict dependencies (e.g., `torch<2`).

**Root Cause:** The `pyproject.toml` file in the official `AlignScore` repository enforced outdated constraints that conflicted with modern `transformers` and `torch` packages used by the rest of the application.

**Fix:** Created an automated `install_alignscore.py` script that clones the repository, forcefully patches `pyproject.toml` to remove the `<2` constraint on `torch`, updates `model.py` to import `AdamW` from `torch.optim` instead of `transformers`, and installs the patched version in editable mode.

---

### Issue 10: LLM Temporal Hallucination ("Saying it is 2024")

**Symptom:** The LLM failed to understand relative time questions and insisted the current year was 2024 (or its knowledge cutoff date).

**Root Cause:** LLMs have static knowledge cutoffs and do not inherently know the system time unless provided in the context.

**Fix:** Updated `generation.py` to call `time.strftime('%Y-%m-%d %H:%M:%S')` and dynamically inject the current, live datetime into the system prompt behind the scenes for every query.

---

### Issue 11: Ungrounded Queries Wasting LLM Tokens

**Symptom:** Queries like "how to make a bomb" or entirely ungrounded claims were being sent to the LLM. The system relied on the LLM's own safety refusal (which is slow and wastes API quota). AlignScore was checking the output *after* generation.

**Root Cause:** AlignScore was originally designed as a post-generation checker (LLM Output vs Context) rather than a pre-generation gate (Query vs Context).

**Fix:** Restructured the generation pipeline in `generation.py`. AlignScore now evaluates the user's query against the retrieved context *before* the LLM call. If there's no alignment, the pipeline short-circuits immediately with a `FAIL` severity. We also updated the refusal detection markers to catch all Gemini refusal phrases, and explicitly set up AlignScore to use a local `AlignScore-base.ckpt` file with batch size 16.

---

## Running the System

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your GEMINI_API_KEY

# Start the server
python -m uvicorn controlplane.api.server:app --reload

# Run tests
python -m pytest

# Access the dashboard
# http://127.0.0.1:8000/dashboard/
```

---

## Test Suite

The project includes **67 unit tests** covering all pipeline stages:

| Test File | Coverage |
|-----------|----------|
| `test_cache_metrics.py` | Semantic cache hashing, storage, lookup, metrics |
| `test_generation_repair.py` | Format validation, severity routing, grounding, repair loop |
| `test_ingress.py` | Jailbreak detection, PII masking, intent classification, constraint decomposition |
| `test_retrieval.py` | Metadata filters, token estimation, context compression, mock chunks |

All 67 tests currently pass ✅

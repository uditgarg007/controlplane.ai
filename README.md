# ControlPlane.ai

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.0+-EE4C2C.svg)](https://pytorch.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests Passing](https://img.shields.io/badge/tests-67%2F67%20passed-brightgreen.svg)](tests/)

**ControlPlane.ai** is an enterprise-grade AI security, guardrails, and governance middleware platform designed to intercept, route, filter, and repair LLM generations in real time. Sitting as an intelligent proxy between client applications and large language models (such as Google Gemini), ControlPlane enforces zero-trust safety constraints, factual grounding verification, token economics optimization, demographic bias auditing, and human-in-the-loop escalations.

---

## 📑 Table of Contents

1. [Executive Overview](#-executive-overview)
2. [Key Capabilities](#-key-capabilities)
3. [Solution Architecture](#-solution-architecture)
4. [Pipeline Stages Deep-Dive](#-pipeline-stages-deep-dive)
5. [Implementation Approach & Engineering Decisions](#-implementation-approach--engineering-decisions)
6. [Tech Stack & Dependencies](#-tech-stack--dependencies)
7. [Getting Started & Execution Instructions](#-getting-started--execution-instructions)
8. [Interactive Dashboards](#-interactive-dashboards)
9. [API Reference & Usage Examples](#-api-reference--usage-examples)
10. [Repository Structure](#-repository-structure)
11. [Verification & Testing](#-verification--testing)
12. [License](#-license)

---

## 🎯 Executive Overview

Production LLM applications face critical vulnerabilities:
- **Hallucinations & Ungrounded Claims:** LLMs confidently invent facts not supported by corporate knowledge bases.
- **Adversarial Ingress (Prompt Injections & Jailbreaks):** Malicious actors manipulate prompts or attempt slow, compounding multi-turn attacks.
- **Data Privacy & Compliance (PII Leakage):** Sensitive customer data entering prompts or model responses violates regulatory frameworks (GDPR, HIPAA).
- **Inference Costs & Latency:** Redundant queries and oversized retrieval contexts inflate token bills and degrade response times.
- **Uncontrolled Tool Execution:** Agentic tool calls risk running destructive commands or accessing unauthorized endpoints.
- **Demographic Bias & Unfairness:** Models may output discriminatory or skewed responses without real-time observability.

**ControlPlane.ai solves these challenges with a modular, 5-stage middleware pipeline backed by dynamic policy governance, semantic caching, pre/post-generation grounding checks, and an automated self-healing repair loop.**

---

## ⚡ Key Capabilities

- 🛡️ **Zero-Trust Ingress Security:** Multi-signal prompt injection detection, heuristic and BART zero-shot intent classification, Presidio PII anonymization, and compounding multi-turn session risk tracking.
- ⚡ **Semantic & Exact Caching:** Dual-tier exact hash (Redis) and fuzzy embedding cache for sub-millisecond responses and 100% token savings on repeated intents.
- 🔀 **Adaptive Retrieval Routing:** Context-aware routing between FAISS vector search, Neo4j GraphRAG, and real-time DuckDuckGo web search fallback.
- 📉 **LLMLingua Context Compression:** Automatic context compacting to reduce token footprint by up to 50–70% before prompt construction.
- 🎯 **AlignScore Factual Grounding:** Pre-generation and post-generation NLI-based factual consistency scoring against retrieved context to eliminate hallucinations.
- 🔁 **Self-RAG / CRAG Repair Loop:** Self-healing corrective feedback loop with AI Judge failure diagnosis, query rewriting, and automatic channel escalation.
- ⚖️ **Dynamic Policy Engine & Active Feedback Loops:** SQLite-backed configurable policy profiles (`customer_support`, `internal_copilot`, `regulated_decision`) with automated threshold relaxation based on false-positive rates.
- 🛑 **Execution Guardrails:** Proactive inspection and sandboxing of agentic tool calls to prevent destructive command injection or unauthorized network requests.
- 🧑‍⚖️ **Async AI-as-Judge & Bias Observability:** Non-blocking background demographic bias and stereotyping evaluations without adding latency to the critical path.
- 🚨 **Human-in-the-Loop (HITL) Quarantine Queue:** Automated escalation of borderline or high-risk responses to an interactive administrative review console.

---

## 🏗️ Solution Architecture

The following diagram illustrates the lifecycle of a query flowing through the ControlPlane.ai middleware:

```
                                  [ User Request ]
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │      Governance & Policy Engine       │
                     │  • Maps UserContext to PolicyProfile  │
                     │  • Dynamic SQLite policy thresholds   │
                     │  • Active Feedback Loop Auto-tuning   │
                     └───────────────────┬───────────────────┘
                                         │ Active Policy
                                         ▼
                     ┌───────────────────────────────────────┐
                     │       Stage 0: Semantic Cache         │
                     │  • Exact Hash + Vector Similarity     │
                     └───────┬───────────────────────┬───────┘
                             │ HIT                   │ MISS
                             ▼                       ▼
                   [ Return 100% Saved ] ┌───────────────────────────────────────┐
                                         │       Stage 1: Ingress Guard          │
                                         │  • Multi-Turn Session Risk Compounder │
                                         │  • Presidio PII Masking Engine        │
                                         │  • BART Zero-Shot Intent Classifier   │
                                         │  • Constraint Decomposition           │
                                         └───────────────────┬───────────────────┘
                                                             │
                                                     [ Blocked? ] ──► YES ──► [ Blocked Response + Audit Log ]
                                                             │ NO
                                                             ▼
                                         ┌───────────────────────────────────────┐
                                         │      Stage 2: Retrieval Routing       │
                                         │  • Semantic Query ──► FAISS Vector    │
                                         │  • Multi-Hop Query ─► Neo4j GraphRAG  │
                                         │  • Fallback ────────► Live Web Search │
                                         │  • LLMLingua Context Compression      │
                                         └───────────────────┬───────────────────┘
                                                             │
                                                             ▼
                                         ┌───────────────────────────────────────┐
                                         │    Stage 3: Generation & Grounding    │
                                         │  • Pre-Gen Grounding Verification     │
                                         │  • LLM Generation (Gemini / OpenAI)   │
                                         │  • LettuceDetect Format Validation    │
                                         │  • AlignScore Grounding Evaluation    │
                                         │  • Severity Verdict: PASS/WARN/FAIL   │
                                         └───────────────────┬───────────────────┘
                                                             │
                                           ┌─────────────────┴─────────────────┐
                                           │                                   │
                                   [ PASS / Clean ]                    [ FAIL / WARN ]
                                           │                                   │
                                           │                                   ▼
                                           │                   ┌───────────────────────────────┐
                                           │                   │     Stage 4: Repair Loop      │
                                           │                   │  • AI Judge Failure Diagnosis │
                                           │                   │  • Query Rewriter (Rephrase)  │
                                           │                   │  • Retrieval Channel Switch   │
                                           │                   │  • Bounded Self-RAG Iteration │
                                           │                   └───────────────┬───────────────┘
                                           │                                   │
                                           │           ┌───────────────────────┴───────────────────────┐
                                           │           │                                               │
                                           │      [ Repaired ]                                   [ QUARANTINE ]
                                           │           │                                               │
                                           │           │                                               ▼
                                           │           │                               ┌───────────────────────────────┐
                                           │           │                               │   Stage 5: HITL Quarantine    │
                                           │           │                               │   • Intercepted for Review    │
                                           │           │                               │   • Approve / Redact / Block  │
                                           │           │                               └───────────────────────────────┘
                                           ▼           ▼
                     ┌───────────────────────────────────────────────────────────┐
                     │                Parallel Observability Layer               │
                     │  • Async AI-as-Judge Demographic Bias Monitor             │
                     │  • Token Economics & Cost Tracking                        │
                     │  • ExecutionGuard Agentic Tool Validation                 │
                     │  • SQLite Audit Ledger & Live Prometheus / KPI Telemetry  │
                     └─────────────────────────────┬─────────────────────────────┘
                                                   │
                                                   ▼
                                           [ Final Response ]
```

---

## 🔍 Pipeline Stages Deep-Dive

### Stage 0: Dynamic Policy Engine & Semantic Cache
- **Policy Engine (`governance.py`):** Dynamically loads safety thresholds based on the requester's role (`ADMIN`, `INTERNAL`, `EXTERNAL`) and context.
  - Profiles: `customer_support` (low latency, balanced checks), `internal_copilot` (developer tooling, relaxed PII), and `regulated_decision` (strict compliance, mandatory quarantine on WARN).
- **Active Feedback Loops:** Monitors Human-in-the-Loop review resolutions. If false-positive rates exceed 30%, it automatically tunes thresholds to prevent bottlenecking.
- **Semantic Caching (`semantic_cache.py`):** Checks Redis for exact SHA-256 matches and in-process cosine similarity for semantically identical questions, delivering instantaneous answers with zero LLM token cost.

### Stage 1: Ingress Guard & Constraint Decomposition (`ingress.py`, `input_guard.py`)
- **Compounding Session Risk:** Multi-turn tracker in `session.py` that accumulates risk across sequential interactions to intercept distributed or incremental jailbreak attempts.
- **Jailbreak & Attack Interception:** Regex heuristics combined with entropy anomaly detection and intent classification to block malicious instructions.
- **Presidio PII Masking:** Detects and redacts emails, phone numbers, credit cards, and social security numbers before context assembly.
- **Constraint Decomposition:** Separates query intent from hard metadata pre-filters (e.g., date ranges, category restrictions).

### Stage 2: Advanced Retrieval & Context Compression (`retrieval.py`, `web_search.py`)
- **Dual-Channel Retrieval:** Routes semantic questions to FAISS vector search and complex relational questions to Neo4j GraphRAG.
- **Real-Time Web Fallback:** If local index retrieval confidence is low or knowledge is missing, the system dynamically queries DuckDuckGo (`ddgs`) for real-time ground truth.
- **LLMLingua Context Compression:** Strips redundant tokens from retrieved snippets while preserving semantic density, reducing input token overhead by 50–70%.

### Stage 3: Generation & In-Flight Grounding (`generation.py`)
- **Pre-Generation Grounding Gate:** Checks retrieved context quality prior to LLM invocation, preventing unnecessary token usage when context is missing.
- **Target LLM Inference:** Calls Gemini or OpenAI-compatible backends with dynamic system prompts containing live date awareness.
- **LettuceDetect Format Validation:** Enforces strict structural checks (JSON schema validation, minimum length, sycophancy avoidance).
- **AlignScore Verification:** Evaluates the generated claim against the context using a local RoBERTa-based NLI factual consistency model.
- **Severity Routing:** Assigns `PASS`, `WARN`, `FAIL`, or `QUARANTINE`.

### Stage 4: Corrective Self-RAG / CRAG Repair Loop (`repair.py`)
- **Failure Diagnosis (AI Judge):** Pinpoints the precise cause of failure (hallucination, missing context, malformed structure).
- **Bounded Self-Healing Loop:** Recursively attempts to repair the output (up to 3 iterations):
  1. *Iteration 1:* Rephrase query + retry vector retrieval with altered temperature.
  2. *Iteration 2:* Escalate to live web search fallback.
  3. *Iteration 3:* Force structural regeneration or route to HITL Quarantine.

### Stage 5: Human-in-the-Loop & Async Observability (`hitl.html`, `bias_monitor.py`, `execution_guard.py`)
- **HITL Quarantine:** Flagged responses are held in `governance.db`. Administrators can review, redact, approve, or permanently block outputs from the dedicated web portal.
- **Async AI-as-Judge Bias Auditing:** Offloads demographic, gender, and racial bias analysis to background threads to ensure zero impact on user-facing latency.
- **Execution Guard (`execution_guard.py`):** Sandboxes and inspects agentic tool calls (e.g., bash execution, database queries, URL fetches) against strict whitelists and dangerous pattern filters.

---

## 🛠️ Tech Stack & Dependencies

| Category | Technology / Library | Purpose |
| :--- | :--- | :--- |
| **Framework & API** | FastAPI, Uvicorn, Pydantic | High-performance asynchronous API server |
| **LLM Inference** | Google Gemini (via OpenAI client compatibility) | Primary LLM generation engine |
| **Factual Grounding** | AlignScore (`RoBERTa-base` checkpoint), spaCy | NLI-based factual consistency & hallucination detection |
| **Intent Classification** | Hugging Face Transformers (`facebook/bart-large-mnli`) | Zero-shot query classification |
| **Privacy & PII** | Microsoft Presidio Analyzer & Anonymizer | Entity recognition and redaction |
| **Vector Search** | FAISS, Sentence-Transformers (`all-MiniLM-L6-v2`) | Dense vector indexing and similarity retrieval |
| **Web Retrieval** | `duckduckgo-search` (`ddgs`) | Live web search fallback for dynamic knowledge |
| **Context Compression** | LLMLingua | Token compaction and cost reduction |
| **Storage & Governance** | SQLite, Redis (optional) | Policy profiles, audit ledger, HITL queue, and cache |
| **Observability** | Prometheus Client, Loguru | Latency telemetry, token economics, and error tracing |
| **Frontend UI** | HTML5, Vanilla Modern CSS, JavaScript ES6 | Interactive Control Plane dashboard, Policy UI, HITL console |

---

## 🚀 Getting Started & Execution Instructions

### Prerequisites
- **Python 3.10+** (Python 3.11 recommended)
- **Git**
- A **Google Gemini API Key** (from [Google AI Studio](https://aistudio.google.com/))

---

### Step 1: Clone the Repository

```bash
git clone https://github.com/uditgarg007/controlplane.ai.git
cd controlplane.ai
```

---

### Step 2: Create and Activate Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

### Step 3: Install Core Dependencies

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

---

### Step 4: Install AlignScore & Model Checkpoints

ControlPlane includes an automated setup script that clones, patches modern PyTorch/transformers compatibility, and installs AlignScore:

```bash
python install_alignscore.py
```

*Note: Ensure the AlignScore checkpoint `AlignScore-base.ckpt` is located in `checkpoints/AlignScore-base.ckpt` (or it will automatically download/fallback gracefully).*

To verify AlignScore installation:
```bash
python test_alignscore.py
```

---

### Step 5: Configure Environment Variables

Copy the sample environment file:

```bash
cp .env.example .env
```

Open `.env` and configure your API keys:

```ini
# Core LLM Configuration
GEMINI_API_KEY=your_google_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Caching & Databases (Optional / Defaults provided)
REDIS_HOST=localhost
REDIS_PORT=6379
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Hugging Face Token (Optional, for higher rate limits)
HF_TOKEN=your_huggingface_token
```

---

### Step 6: Build the Vector Knowledge Index

Build the sample FAISS vector index with enterprise policy and technical documentation:

```bash
python scripts/build_index.py
```

---

### Step 7: Launch the Server

Start the FastAPI application via Uvicorn:

```bash
python -m uvicorn controlplane.api.server:app --host 127.0.0.1 --port 8000 --reload
```

Once running:
- **API Base:** `http://127.0.0.1:8000`
- **Interactive OpenAPI Docs (Swagger):** `http://127.0.0.1:8000/docs`
- **Live Metrics JSON:** `http://127.0.0.1:8000/api/metrics`

---

## 🖥️ Interactive Dashboards

ControlPlane includes three dedicated web interfaces accessible directly in your browser:

### 1. Main Control Plane Dashboard
**URL:** `http://127.0.0.1:8000/dashboard/index.html`
- **Interactive Query Console:** Test queries with selectable user roles (`EXTERNAL`, `INTERNAL`, `ADMIN`) and session IDs.
- **Stage Waterfall:** Real-time visual trace of Ingress ➔ Retrieval ➔ Generation ➔ AlignScore ➔ Repair stages.
- **Grounding Gauge:** Live AlignScore consistency meter.
- **Token Economics:** Real-time token savings and compression ratio calculation.

### 2. Dynamic Policy Engine
**URL:** `http://127.0.0.1:8000/dashboard/policy.html`
- Adjust AlignScore thresholds, composite risk triggers, and PII masking on the fly.
- Switch policies across `customer_support`, `internal_copilot`, and `regulated_decision`.
- View active feedback loop calibrations.

### 3. Human-in-the-Loop (HITL) Review Queue
**URL:** `http://127.0.0.1:8000/dashboard/hitl.html`
- Review intercepted and quarantined generations.
- Inspect original prompt, flagged output, and violation reason.
- Submit administrative actions: **Approve**, **Redact & Release**, or **Block**.

---

## 📡 API Reference & Usage Examples

### 1. Submit Query (`POST /query`)

**Request:**
```bash
curl -X POST "http://127.0.0.1:8000/query" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "What are the compliance rules for customer data retention?",
       "user_context": {
         "user_id": "user_1024",
         "role": "external"
       },
       "session_id": "session_abc123"
     }'
```

**Response:**
```json
{
  "query_id": "8f03c02d-94c8-4720-9ee4-8393fa114df3",
  "final_answer": "Customer data must be retained for 7 years according to corporate compliance guidelines...",
  "align_score": 0.89,
  "repair_triggered": false,
  "repair_iterations": 0,
  "total_latency_ms": 420.5,
  "latency_breakdown": {
    "cache": 1.2,
    "ingress": 18.4,
    "retrieval": 45.1,
    "generation": 355.8
  },
  "guard_verdict": "PASS",
  "token_economics": {
    "raw_token_count": 820,
    "compressed_token_count": 310,
    "compression_ratio": 0.622,
    "source_channel": "vector"
  }
}
```

---

### 2. Fetch Real-Time Metrics (`GET /api/metrics`)

```bash
curl -X GET "http://127.0.0.1:8000/api/metrics"
```

---

### 3. Update Policy Configuration (`PUT /api/policies/{name}`)

```bash
curl -X PUT "http://127.0.0.1:8000/api/policies/customer_support" \
     -H "Content-Type: application/json" \
     -d '{
       "align_score_threshold": 0.65,
       "guard_block_composite_threshold": 0.55,
       "guard_block_signal_threshold": 0.80,
       "pii_masking_enabled": true,
       "quarantine_on_warn": true,
       "latency_priority": "low",
       "assurance_level": "medium"
     }'
```

---

## 📁 Repository Structure

```
controlplane.ai/
├── controlplane/                  # Core Python package
│   ├── api/
│   │   ├── __init__.py
│   │   └── server.py              # FastAPI server routes & REST endpoints
│   ├── cache/
│   │   ├── __init__.py
│   │   └── semantic_cache.py      # Dual-tier exact hash + vector similarity cache
│   ├── core/
│   │   ├── __init__.py
│   │   ├── execution_guard.py     # Agentic tool call sandboxing & safety checks
│   │   ├── generation.py          # Stage 3: LLM generation & AlignScore verification
│   │   ├── governance.py          # PolicyEngine, SQLite audit ledger & feedback loops
│   │   ├── ingress.py             # Stage 1: PII, intent, and jailbreak detection
│   │   ├── input_guard.py         # Ingress risk scoring & Presidio integrations
│   │   ├── judge.py               # AI-as-Judge failure diagnosis pattern
│   │   ├── repair.py              # Stage 4: Corrective Self-RAG/CRAG repair loop
│   │   └── retrieval.py           # Stage 2: FAISS, GraphRAG & LLMLingua compression
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── web_search.py          # DuckDuckGo fallback retrieval integration
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── bias_monitor.py        # Asynchronous AI-as-Judge demographic bias auditor
│   │   └── metrics.py             # Prometheus counters & live KPI aggregations
│   ├── config.py                  # Pydantic schemas, enums, and system configurations
│   ├── pipeline.py                # Central orchestrator connecting all 5 stages
│   └── session.py                 # Multi-turn session risk accumulation & history
├── dashboard/                     # Web interface files
│   ├── dashboard.css              # Control plane design system & styling
│   ├── dashboard.js               # Main dashboard controller & metrics polling
│   ├── hitl.html                  # Human-in-the-Loop review queue interface
│   ├── hitl.js                    # HITL decision submission logic
│   ├── index.html                 # Main telemetry & query playground UI
│   ├── policy.html                # Dynamic policy configuration UI
│   └── policy.js                  # Policy updating logic
├── data/                          # Data files & indices
│   ├── faiss.index                # Pre-built FAISS vector index
│   └── faiss_meta.json            # Vector chunk metadata
├── scripts/
│   └── build_index.py             # Script to generate FAISS vector embeddings
├── tests/                         # Pytest test suite (67 unit & integration tests)
│   ├── test_cache_metrics.py      # Cache & metrics calculation tests
│   ├── test_generation_repair.py  # Generation, validation & repair loop tests
│   ├── test_ingress.py            # Jailbreak, PII & intent classification tests
│   └── test_retrieval.py          # Vector retrieval & compression tests
├── .env.example                   # Example environment variable configuration
├── .gitignore                     # Git exclusion rules
├── install_alignscore.py          # Automated AlignScore installer & compatibility patcher
├── pytest.ini                     # Pytest configuration
├── requirements.txt               # Project Python dependencies
├── test_alignscore.py             # Checkpoint verification test
└── README.md                      # Project documentation
```

---

## 🧪 Verification & Testing

ControlPlane.ai comes with a comprehensive automated test suite covering all 5 stages of the pipeline:

Run all tests:
```bash
pytest -v
```

### Test Coverage Highlights:
- **Jailbreak Detection:** Verifies interception of known injection patterns and adversarial prompt templates.
- **PII Masking:** Confirms stripping of emails, phone numbers, and SSNs.
- **Intent Classification:** Validates correct routing across semantic, multi-hop, and web channels.
- **Grounding Calculations:** Tests trigram overlap and AlignScore threshold logic.
- **Repair Termination:** Asserts that the Self-RAG repair loop respects bounded iteration limits and terminates on first PASS.
- **Cache Determinism:** Validates hash collision resistance and cache hit rates.

---

## 📄 License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

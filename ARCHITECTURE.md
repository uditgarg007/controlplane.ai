# ControlPlane.ai — Architecture

## Pipeline Overview

```
User Query
    │
    ▼
┌──────────────────────────────────────────┐
│  Governance & Policy Engine              │
│  • Maps UserContext to PolicyProfile     │
│  • Sets thresholds dynamically via UI    │
│  • Feedback loops auto-adjust policies   │
└────────────────┬─────────────────────────┘
                 │ policy
                 ▼
┌──────────────────────────────────────────┐
│  Stage 1: Ingress & Decomposer          │
│  • Multi-turn Session Risk Compounder   │
│  • Intent Classification (BERT)         │
│  • PII Masking & Malicious Content Check│
└────────────────┬─────────────────────────┘
                 │ clean_query + constraints
                 ▼
┌──────────────────────────────────────────┐
│  Semantic Cache (Parallel)              │
│  • Exact + fuzzy cache hit              │
│  • Returns instantly with 100% savings  │
└────────────────┬─────────────────────────┘
                 │ cache miss → continue
                 ▼
┌──────────────────────────────────────────┐
│  Stage 2: Retrieval Routing             │
│  • Semantic → FAISS                     │
│  • Multi-hop → GraphRAG                 │
│  • Context Compression (LLMLingua)      │
└────────────────┬─────────────────────────┘
                 │ pre_compacted_context
                 ▼
┌──────────────────────────────────────────┐
│  Stage 3: Generation & Validation       │
│  • AlignScore (Pre-gen grounding)       │
│  • LLM Inference                        │
│  • Output Validator (format)            │
│  • Severity Routing Engine              │
└────────────────┬─────────────────────────┘
                 │ pass / fail
        ┌────────┴────────┐
        ▼                 ▼
     PASS               FAIL
        │                 │
        │    ┌────────────▼───────────────┐
        │    │  Stage 4: Repair Loop      │
        │    │  • CRAG/Self-RAG Judge     │
        │    │  • Query Rewriter          │
        │    │  • Web Search Fallback     │
        │    │  • Bounded Iteration       │
        │    └────────────┬───────────────┘
        │                 │ repaired output
        └────────┬────────┘
                 ▼
┌──────────────────────────────────────────┐
│  Stage 5: HITL Intercept                │
│  • If severity == QUARANTINE            │
│  • Enqueue to hitl_queue for review     │
└────────────────┬─────────────────────────┘
                 ▼
┌──────────────────────────────────────────┐
│  Parallel Observability Layer           │
│  • AI-as-Judge Bias Monitor (Async)     │
│  • Metrics Dashboard (Live KPI)         │
│  • Token Economics (Cache Savings)      │
│  • Audit Logs (SQLite)                  │
└────────────────┬─────────────────────────┘
                 │
                 ▼
           Final Response
```

## Module Map

```
controlplane/
├── core/
│   ├── ingress.py          # Stage 1 + Session Risk
│   ├── retrieval.py        # Stage 2
│   ├── generation.py       # Stage 3
│   ├── repair.py           # Stage 4
│   ├── governance.py       # Policy, HITL DB & Feedback Loops
│   └── judge.py            # AI-as-Judge Pattern
├── cache/
│   └── semantic_cache.py
├── observability/
│   ├── metrics.py
│   └── bias_monitor.py     # Async Bias & AI Judge Caller
├── api/
│   └── server.py           # FastAPI entrypoint
└── dashboard/
    ├── policy.html         # Dynamic Policy UI
    ├── policy.js           # Policy UI Logic
    └── (frontend)
```

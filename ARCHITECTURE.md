# ControlPlane.ai — Architecture

## Pipeline Overview

```
User Query
    │
    ▼
┌─────────────────────────────────────┐
│  Governance & Policy Engine         │
│  • Maps UserContext to PolicyProfile│
│  • Sets thresholds dynamically      │
└──────────────────┬──────────────────┘
                   │ policy
                   ▼
┌─────────────────────────────────────┐
│  Stage 1: Ingress & Decomposer      │
│  • Intent Classification (BERT)     │
│  • PII Masking                      │
│  • Constraint Decomposition         │
└──────────────────┬──────────────────┘
                   │ clean_query + constraints
                   ▼
┌─────────────────────────────────────┐
│  Semantic Cache (Parallel)          │
│  • Exact + fuzzy cache hit          │
│  • Returns instantly if hit         │
└──────────────────┬──────────────────┘
                   │ cache miss → continue
                   ▼
┌─────────────────────────────────────┐
│  Stage 2: Retrieval Routing         │
│  • Semantic → FAISS                 │
│  • Multi-hop → GraphRAG             │
│  • Context Compression (LLMLingua)  │
└──────────────────┬──────────────────┘
                   │ pre_compacted_context
                   ▼
┌─────────────────────────────────────┐
│  Stage 3: Generation & Validation   │
│  • AlignScore (Pre-gen grounding)   │
│  • LLM Inference                    │
│  • Output Validator (format)        │
│  • Severity Routing Engine          │
└──────────────────┬──────────────────┘
                   │ pass / fail
          ┌────────┴────────┐
          ▼                 ▼
       PASS               FAIL
          │                 │
          │                 ▼
          │    ┌─────────────────────────┐
          │    │  Stage 4: Repair Loop   │
          │    │  • CRAG/Self-RAG Judge  │
          │    │  • Query Rewriter       │
          │    │  • Web Search Fallback  │
          │    │  • Bounded Iteration    │
          │    └────────────┬────────────┘
          │                 │ repaired output
          └────────┬────────┘
                   ▼
┌─────────────────────────────────────┐
│  Stage 5: HITL Intercept            │
│  • If severity == QUARANTINE        │
│  • Enqueue to governance.db         │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│  Parallel Observability Layer       │
│  • Bias Monitor (AIF360)            │
│  • Metrics Dashboard                │
│  • Token Economics Tracker          │
│  • Audit Logs (SQLite)              │
└──────────────────┬──────────────────┘
                   │
                   ▼
             Final Response
```

## Module Map

```
controlplane/
├── core/
│   ├── ingress.py          # Stage 1
│   ├── retrieval.py        # Stage 2
│   ├── generation.py       # Stage 3
│   ├── repair.py           # Stage 4
│   └── governance.py       # Policy & HITL DB
├── cache/
│   └── semantic_cache.py
├── observability/
│   ├── metrics.py
│   └── bias_monitor.py
├── api/
│   └── server.py           # FastAPI entrypoint
└── dashboard/
    └── (frontend)
```

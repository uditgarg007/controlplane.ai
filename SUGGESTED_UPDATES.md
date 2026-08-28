# ControlPlane.ai — Suggested Updates

## Current Status (August 2026)

The pipeline is **functional and tested** with 67/67 tests passing. The system successfully handles conversational queries, general knowledge questions, web retrieval fallbacks, and grounded RAG queries. AlignScore, Web Search (DuckDuckGo via ddgs), and Redis-based Semantic Caching are fully integrated and operational. Below are prioritised improvements split into **immediate actions** and **future roadmap**.

---

## ✅ Recently Completed

- **Governance & Policy Engine:** Implemented `PolicyProfile` to dynamically scale AlignScore thresholds and rules based on user roles (`strict_external` vs `relaxed_internal`). Created local SQLite `governance.db` to store `audit_logs` and a Human-In-The-Loop (`hitl_queue`) for QUARANTINED requests.
- **Pre-generation Grounding Gate:** Restructured the pipeline to run AlignScore *before* LLM inference, short-circuiting ungrounded queries immediately to save API tokens and time. Configured AlignScore to use a local `AlignScore-base.ckpt` with batch size 16.
- **AlignScore Hallucination Detection:** Successfully patched and installed AlignScore for high-fidelity NLI-based semantic grounding.
- **Web Search Retrieval Channel:** Fully integrated real-time web fallback using `ddgs`. Queries outside the local index seamlessly route to the web and pull live context.
- **LLMLingua Context Compression:** Integrated and functioning to maintain token efficiency for web results and retrieved context.
- **HuggingFace Auth & Dependency Conflicts:** `HF_TOKEN` configured, and modern PyTorch environments patched for compatibility.
- **Date Awareness:** LLM system prompt dynamically injects the current live date, solving past knowledge-cutoff errors.

---

## 🔴 Immediate Updates (Do Now)

### 1. Build Dashboard UI for HITL Queue

**Priority:** High
**Why:** The backend now routes flagged responses to `hitl_queue` with `SeverityLevel.QUARANTINE`. Administrators need a UI to review these intercepted prompts/responses to approve, redact, or permanently block them.
**How:** Build a simple HTML/JS page that fetches from `hitl_queue` via a new `/api/hitl` endpoint, and submits decisions.
**Effort:** 2-3 hours
**Files:** `controlplane/api/server.py`, `dashboard/hitl.html`

---

### 1b. Add Document Ingestion API Endpoint

**Priority:** High
**Why:** Currently, the FAISS index is built statically via `scripts/build_index.py`. Users need a live `/ingest` API endpoint to feed PDFs, text files, or URLs into the FAISS index dynamically.

**Suggested endpoint:**
```json
POST /ingest
Body: { "documents": [{"text": "...", "metadata": {...}}] }
Response: { "indexed": 5, "total_chunks": 23 }
```

**Effort:** 3–4 hours
**Files:** New `controlplane/core/ingest.py`, update `controlplane/api/server.py`

---

### 2. Upgrade to a Paid Gemini Tier (or Get a New API Key)

**Priority:** High (for production use)
**Why:** The free tier is limited to 1,500 requests/day on `gemini-3.5-flash-lite`. For any real-world use or demo, this will be exhausted quickly.

**Options:**
| Tier | Rate Limit | Cost |
|------|-----------|------|
| Free | 1,500 RPD / 15 RPM | $0 |
| Pay-as-you-go | Unlimited RPD / 2,000 RPM | ~$0.075 per 1M input tokens |

**Action:** Enable billing in Google AI Studio → switch `GEMINI_MODEL` back to `gemini-2.5-flash` or `gemini-3.5-flash` for better quality.

---

### 3. Add Web Search Caching Layer

**Priority:** Medium
**Why:** Currently, the top-level semantic cache stores the final answers, but intermediate web searches via `ddgs` are un-cached. If the final answer cache misses but the web search intent is identical, we waste time re-fetching from DuckDuckGo.
**How:** Wrap the web search tool in a Redis-backed caching decorator with a TTL (e.g., 1 hour).
**Effort:** 1–2 hours
**Files:** `controlplane/integrations/web_search.py`

---

### 4. Implement PDF & OCR Parsing for Indexing

**Priority:** Medium
**Why:** The FAISS index currently handles raw text. To be enterprise-ready, the system must parse complex PDFs (tables, images, charts).
**How:** Integrate `unstructured` or `PyMuPDF` into the ingestion pipeline to automatically chunk complex documents before FAISS embedding.
**Effort:** 4–5 hours
**Files:** `controlplane/core/ingest.py`

## 🟡 Short-Term Updates (Next 1–2 Weeks)



### 7. Add Streaming Response Support

**Priority:** Medium
**Why:** Currently the API returns the full response only after the entire pipeline completes. For long answers, this feels slow. Streaming would show tokens as they're generated.

**How:**
- Use FastAPI's `StreamingResponse` with `SSE` (Server-Sent Events)
- Set `stream=True` in the OpenAI client call
- Yield tokens to the frontend as they arrive

**Effort:** 3–4 hours
**Files:** `controlplane/api/server.py`, `controlplane/core/generation.py`, `dashboard/dashboard.js`

---

### 8. Add Conversation History / Multi-Turn Support

**Priority:** Medium
**Why:** Currently each query is stateless. The system cannot handle follow-up questions like "Tell me more" or "What about the second point?"

**How:**
- Maintain a session-level message history (stored in Redis or in-memory)
- Pass previous turns in the `messages` array to the LLM
- Add a `session_id` parameter to the `/query` endpoint

**Effort:** 4–5 hours
**Files:** `controlplane/api/server.py`, `controlplane/core/generation.py`, new `controlplane/session.py`



### 10. Add Authentication to the API

**Priority:** Medium
**Why:** The API is currently open — anyone with network access can send queries, consume Gemini quota, and view the dashboard.

**Suggested approach:**
- API key-based auth via `X-API-Key` header
- FastAPI `Depends()` middleware for validation
- Store allowed keys in `.env` or a simple JSON file

**Effort:** 2 hours
**Files:** `controlplane/api/server.py`, new `controlplane/auth.py`

---

## 🟢 Future Roadmap (1–3 Months)

### 11. Hybrid Retrieval (Vector + Graph Fusion)

Instead of routing exclusively to FAISS *or* Neo4j based on intent, fuse results from both backends. Use Reciprocal Rank Fusion (RRF) to merge and re-rank chunks from multiple sources for richer context.

---

### 12. Fine-Tune a Lightweight Intent Classifier

Replace the general-purpose BART zero-shot model (~1.6 GB) with a fine-tuned DistilBERT or TinyBERT classifier (~100 MB) trained on your actual query distribution. This would reduce startup time from ~8 seconds to <1 second and improve classification accuracy.

---



### 14. Add Prometheus + Grafana Monitoring

The `prometheus-client` package is already in `requirements.txt`. Expose a `/metrics` endpoint in Prometheus format and connect it to a Grafana dashboard for production-grade observability with alerting.

---

### 15. Deploy with Docker Compose

Create a `docker-compose.yml` that bundles:
- The FastAPI application
- Redis (for caching)
- Neo4j (for graph retrieval)
- Prometheus + Grafana (for monitoring)

This would make the entire system deployable with a single `docker compose up`.

---

### 16. Support Multiple LLM Backends

Abstract the LLM client behind a provider interface so the system can switch between:
- Google Gemini (current)
- OpenAI GPT-4
- Anthropic Claude
- Local models via Ollama

This would eliminate single-vendor lock-in and allow cost optimisation by routing different query types to different models.

---

### 17. Add RAG Evaluation Benchmarks

Integrate evaluation frameworks like RAGAS or DeepEval to continuously measure:
- **Faithfulness** — does the answer stick to the context?
- **Relevancy** — is the retrieved context relevant to the query?
- **Answer Correctness** — is the final answer factually correct?

Run these benchmarks nightly as CI checks against a golden test set.

---

### 18. Implement Role-Based Access Control (RBAC)

For enterprise deployments, add multi-tenant support with role-based permissions:
- **Admin** — full access, can configure models and thresholds
- **User** — can query and view dashboard
- **Viewer** — read-only dashboard access

---

## Summary Priority Matrix

| # | Update | Priority | Effort | Impact |
|---|--------|----------|--------|--------|
| 1 | Document ingestion endpoint | 🔴 High | 3–4h | Enables data loading |
| 2 | Upgrade Gemini tier | 🔴 High | 10min | Removes quota limit |
| 3 | Web Search Caching Layer | 🟡 Medium | 1–2h | Saves DDG time limits |
| 4 | PDF & OCR Parsing | 🟡 Medium | 4–5h | Enterprise readiness |
| 5 | Streaming responses | 🟡 Medium | 3–4h | Better UX |
| 6 | Multi-turn support | 🟡 Medium | 4–5h | Conversation memory |
| 7 | API authentication | 🟡 Medium | 2h | Security |
| 8+ | Future roadmap items | 🟢 Planned | Varies | Enterprise-grade |

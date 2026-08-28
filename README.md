# ControlPlane.ai

ControlPlane.ai is an enterprise-grade AI security and governance middleware platform designed to intercept, route, filter, and repair LLM generations in real-time.

## Overview

Modern AI applications require varying levels of safety, compliance, and governance depending on whether they are user-facing, internal, real-time, or batch-processed. ControlPlane acts as an intelligent proxy sitting between your application and the LLM (like Gemini), applying multi-stage safety checks:

1. **Ingress Filtering (InputGuard):** Scans the raw user query for prompt injection, jailbreaks, toxicity, and entropy anomalies before it ever reaches the LLM. It also handles PII masking (via Presidio) to ensure sensitive data never leaves your infrastructure.
2. **Retrieval (RAG):** Uses FAISS vector search to enrich the query with context.
3. **Generation & Verification (AlignScore):** Calls the LLM to generate an answer, then uses AlignScore to grade the factual consistency of the response against the retrieved context to detect hallucinations.
4. **Corrective Repair Loop:** If a response fails the AlignScore threshold or violates formatting constraints, the pipeline enters a Self-RAG/CRAG repair loop, asking the LLM to recursively fix its own mistakes within a strict iteration budget.
5. **Governance & Human-in-the-Loop (HITL):** Applies role-based policies. Borderline responses (WARN state) can be escalated to a QUARANTINE queue where administrators can manually Review, Approve, Redact, or Block the response.

## Getting Started

### Prerequisites

- Python 3.10+
- `git`
- `winget` (for optional CLI tools on Windows)
- A Gemini API Key (`GEMINI_API_KEY`)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/uditgarg007/controlplane.ai.git
   cd controlplane.ai
   ```

2. **Set up the virtual environment:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Spacy and AlignScore Checkpoints:**
   AlignScore requires specific model weights to run the factual consistency checks.
   ```bash
   python -m spacy download en_core_web_lg
   python install_alignscore.py
   ```

5. **Set up Environment Variables:**
   Copy the example environment file and add your keys:
   ```bash
   cp .env.example .env
   ```
   *Make sure to add your `GEMINI_API_KEY` to the `.env` file.*

### Running the Server

Start the FastAPI server via Uvicorn:

```bash
python -m uvicorn controlplane.api.server:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

### Accessing the Dashboard

ControlPlane includes a beautiful, interactive frontend dashboard to visualize real-time pipeline metrics, token economics, and the RAG process.

Navigate your browser to:
**http://127.0.0.1:8000/dashboard/**

### Human-in-the-Loop (HITL) Queue

To review quarantined queries, access the Review Queue via the top right corner of the main dashboard, or navigate to:
**http://127.0.0.1:8000/dashboard/hitl.html**

From here, administrators can see the original user query, view the LLM's flagged generation, and securely Approve, Redact, or Block the output.

## Architecture

For a deep dive into the 4-stage pipeline, please refer to [ARCHITECTURE.md](ARCHITECTURE.md) and [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## License
MIT License

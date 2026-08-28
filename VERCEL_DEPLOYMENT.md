# ControlPlane.ai — Vercel Deployment Plan

## Overview

Vercel is an excellent platform for deploying frontend applications and lightweight serverless functions. Because ControlPlane.ai is built with **FastAPI**, we can deploy it to Vercel using their Python runtime. 

When deploying a Python API on Vercel, the application is converted into **Serverless Functions**.

> **Note:** Vercel has a hard limit of 250MB for serverless function deployments on the free tier (and 500MB on Pro). Because ControlPlane uses heavy ML libraries (`torch`, `transformers`, `spacy`, `faiss-cpu`), and the newly integrated **AlignScore** which relies on a ~500MB local `AlignScore-base.ckpt` file, deploying this directly to Vercel Serverless is extremely challenging (and likely impossible without offloading).

## Step-by-Step Deployment Guide

### 1. Structure the Project for Vercel

Vercel expects Python entry points to be inside an `api/` directory.

1. Create a new directory named `api` at the root of the project.
2. Inside `api/`, create a file called `index.py`. This will serve as the serverless entry point for Vercel to load the FastAPI application.

**File:** `api/index.py`
```python
from controlplane.api.server import app

# Vercel serverless functions look for the 'app' variable here
```

---

### 2. Configure `vercel.json`

Vercel needs to be told how to route requests to the FastAPI application. Create a `vercel.json` configuration file at the root of the repository.

**File:** `vercel.json`
```json
{
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/index.py"
    }
  ]
}
```

This configuration tells Vercel:
1. Build `api/index.py` using the Python runtime.
2. Route *all* incoming requests (`/(.*)`) to the FastAPI app.

---

### 3. Handle Dependency Size Limits

Vercel Serverless Functions have a size limit (unzipped). Heavy machine learning libraries like `torch` and `transformers` will exceed this limit.

**Strategy to reduce size:**
1. Use CPU-only versions of PyTorch.
2. Offload the heaviest NLP components (if they cause build failures) to external services. **AlignScore's ~500MB local checkpoint (`AlignScore-base.ckpt`) will explicitly break Vercel's ephemeral limits.** You must either disable AlignScore (falling back to Jaccard overlap) via environment flags, or run it on a dedicated inference server.

Create a specific requirements file for Vercel (or modify `requirements.txt`) to explicitly use the CPU-only index for PyTorch. You can instruct Vercel's pip to use a specific index URL in a `build.sh` script, or define it in a `pip.conf`.

Alternatively, if the model weights (e.g., AlignScore, BART zero-shot, sentence-transformers) are downloaded at runtime, they will definitely exceed the 10-second serverless execution timeout or the ephemeral storage limit (512MB).

*To mitigate this on Vercel:*
- Configure HuggingFace libraries to download weights to a persistent cache (hard in serverless) or shift the intent classification / embeddings / hallucination checks to external APIs (e.g., Gemini's embedding models).

---

### 4. Setup Environment Variables

Before deploying, you must configure the production environment variables in the Vercel Dashboard.

Go to **Project Settings > Environment Variables** and add:
- `GEMINI_API_KEY`: Your Gemini API key.
- `GEMINI_MODEL`: `gemini-3.5-flash-lite`
- `NEO4J_URI`: URL for Neo4j Aura (if using remote graph).
- `NEO4J_USER` and `NEO4J_PASSWORD`
- `REDIS_URL`: Remote Redis instance (e.g., Upstash or Vercel KV) since Vercel is stateless.
- `HF_TOKEN`: (Optional) Hugging Face token.

---

### 5. Deploying via Vercel CLI

The easiest way to deploy is using the Vercel CLI.

1. Install the CLI:
   ```bash
   npm i -g vercel
   ```
2. Run the deployment command from the project root:
   ```bash
   vercel
   ```
3. Follow the prompts to link the project. Vercel will upload the code, install dependencies, and build the serverless functions.
4. For production deployment, run:
   ```bash
   vercel --prod
   ```

---

## Challenges to Consider for Serverless FastAPI

While deploying FastAPI to Vercel is straightforward, ControlPlane.ai's specific architecture poses a few challenges in a serverless environment:

1. **Statelessness:** Vercel functions scale down to zero. In-process caching (like the semantic vector cache `_vector_cache`) will be lost between invocations. You must rely solely on the external Redis cache.
2. **Local FAISS Index:** You cannot easily read from a local `./data/faiss.index` file on Vercel because the filesystem is ephemeral. You should either:
   - Store the FAISS index in AWS S3 and download it on startup (adds cold-start latency).
   - Use a managed vector database (like Pinecone, Weaviate, or Qdrant) instead of local FAISS.
3. **Execution Timeouts:** Vercel free tier limits function execution to 10 seconds (Pro is up to 5 minutes). Complex repair loops might take longer than 10 seconds. You may need a Vercel Pro plan or configure edge/background functions.
4. **SQLite Database (Governance):** The local SQLite database (`data/governance.db`) used for audit logs and the HITL queue will NOT persist across serverless invocations. For Vercel deployment, you MUST migrate the `governance.py` connection to a hosted PostgreSQL instance (e.g., Vercel Postgres, Supabase, or Neon).

---

## Alternative: Containerized Deployment (Recommended)

Given the heavy ML dependencies (`torch`, `transformers`) and the need for persistent local vector indexes and fast cold starts, deploying ControlPlane.ai as a Docker container on a container service might be more reliable than Vercel serverless.

**Recommended Container Platforms:**
- **Railway / Render:** Simple Git-based deployment, natively supports Docker and background jobs.
- **Google Cloud Run:** Fully managed serverless containers with longer timeouts and more memory.
- **Hugging Face Spaces:** Ideal for heavy ML Python backends.

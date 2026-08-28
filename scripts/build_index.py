import os
import sys

# Ensure controlplane module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from controlplane.core.retrieval import build_faiss_index

def main():
    print("Preparing documents...")
    documents = [
        {
            "text": "ControlPlane.ai is an intelligent AI middleware designed to safely route, filter, and ground LLM queries.",
            "metadata": {"source": "docs.txt", "topic": "overview"}
        },
        {
            "text": "The ingress stage performs PII masking, intent classification, and constraint decomposition to protect user data.",
            "metadata": {"source": "docs.txt", "topic": "ingress"}
        },
        {
            "text": "The generation stage leverages the Gemini 3.5 Flash model and applies structural formatting checks to ensure reliability.",
            "metadata": {"source": "docs.txt", "topic": "generation"}
        },
        {
            "text": "Financial reports indicate that Q1 2024 revenue grew by 15% compared to Q3 2023, driven by enterprise AI adoption.",
            "metadata": {"source": "financials.pdf", "topic": "financials", "year": 2024}
        },
        {
            "text": "ControlPlane uses an asynchronous bias monitor powered by IBM AIF360 to ensure demographic and algorithmic fairness.",
            "metadata": {"source": "docs.txt", "topic": "observability"}
        },
        {
            "text": "Our mock retrieval system acts as a fallback when FAISS is unavailable, ensuring the application doesn't completely crash.",
            "metadata": {"source": "docs.txt", "topic": "retrieval"}
        }
    ]

    texts = [doc["text"] for doc in documents]
    metadata = [doc["metadata"] for doc in documents]

    index_path = "./data/faiss.index"
    
    print("Building FAISS index...")
    build_faiss_index(index_path, texts, metadata)
    print("Index successfully built and ready for use in ControlPlane.ai!")

if __name__ == "__main__":
    main()

import os
import subprocess
import sys

def setup_environment():
    """Hack to install heavy models in a Gradio space before starting FastAPI"""
    print("Initializing Hugging Face Environment...")
    
    try:
        import spacy
        if not spacy.util.is_package("en_core_web_lg"):
            print("Downloading Spacy en_core_web_lg...")
            subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_lg"], check=True)
    except Exception as e:
        print(f"Spacy setup failed: {e}")

    try:
        import alignscore
    except ImportError:
        print("Installing AlignScore...")
        subprocess.run([sys.executable, "install_alignscore.py"], check=True)

# Run setup before importing the main app
setup_environment()

import uvicorn
from controlplane.api.server import app

if __name__ == "__main__":
    # Hugging Face Spaces routes internal traffic to port 7860
    uvicorn.run(app, host="0.0.0.0", port=7860)

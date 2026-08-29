FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

# Create a non-root user (Hugging Face Spaces requires this)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Copy files and set permissions
COPY --chown=user . .

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Spacy model
RUN python -m spacy download en_core_web_lg

# Install AlignScore
RUN python install_alignscore.py

# Make sure data directory exists and is writable by the user
RUN mkdir -p data

# Expose port for Hugging Face Spaces
EXPOSE 7860

# Start FastAPI on port 7860
CMD ["uvicorn", "controlplane.api.server:app", "--host", "0.0.0.0", "--port", "7860"]

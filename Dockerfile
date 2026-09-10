FROM python:3.12-slim

WORKDIR /app

# build-essential: some sentence-transformers/torch wheels need a compiler
# on certain platforms; curl: used by the healthcheck in docker-compose.yml
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ingest.py and audit_log.py write here at runtime
RUN mkdir -p qdrant_data evals

ENV PYTHONUNBUFFERED=1

# Ingestion and the agent both need GROQ_API_KEY / site URLs at runtime —
# supplied via .env or docker-compose environment, not baked into the image.
CMD ["python", "run_agent.py"]

# Reranker service (D-30). Qwen3-Reranker is NOT served by Ollama (no
# rerank endpoint) and a dedicated cross-encoder runtime (vLLM / TEI) needs
# its own hardware benchmark that was never run — found live (2026-08-17)
# that this CPU-only setup already strains to serve one 4B chat model, so
# the real implementation reuses that same Ollama chat model for LLM-based
# listwise reranking instead (see apps/reranker/main.py's docstring). That
# means this image now needs the same runtime as the API/worker images
# (src.graph.llm_client's httpx/pydantic/tenacity), not just fastapi+uvicorn.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY src ./src
COPY apps/reranker ./apps/reranker

EXPOSE 8081

CMD ["uvicorn", "apps.reranker.main:app", "--host", "0.0.0.0", "--port", "8081"]

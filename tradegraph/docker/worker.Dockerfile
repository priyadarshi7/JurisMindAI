# Worker image — deliberately SEPARATE from the API image (D-16, docs/12).
# Ingestion and research workers are separate deployables (D-16, locked): this
# one image is run as two independently-scaled services, each consuming its
# own Celery queue ("research" / "ingestion") selected via CMD at deploy time —
# see docker-compose.yml / the V4 production topology in docs/12.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY src ./src

# Default entrypoint runs the research queue; the ingestion deployable
# overrides CMD with `--queues=ingestion` (see docs/12 process topology).
CMD ["celery", "--app=src.core.celery_app", "worker", "--loglevel=INFO", "--queues=research"]

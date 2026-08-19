# Ollama model pinning

Per docs/16 Phase 0 checklist: *"Ollama modelfiles in `ops/`, model tags
pinned by digest — an unpinned tag makes every past result irreproducible."*

## Why this directory exists

A run manifest ([docs/17](../../docs/17-ai-configuration-versioning.md))
records `llm_model` and `embedding_model` as part of what makes a research
job or an experiment reproducible. If the tag behind `qwen3:8b` can silently
point at a different set of weights next month, that field stops meaning
anything. Modelfiles here pin a specific digest so "which model produced
this" has one answer, permanently.

## Files

| File | Used for (docs/15 D-1 per-node tiering) |
|---|---|
| `tier-fast.Modelfile` | Planner, Query Decomposer, Evidence Extractor — smaller/faster |
| `tier-strong.Modelfile` | Verifier, Critic, Synthesizer, Citation Validator |
| `embedding.Modelfile` | Dense embeddings (D-2) |

Exact base model + parameter size for each tier is pinned after the D-30
hardware benchmark (Phase 0 decision, tunable 🎛️) — the placeholders below
name the family, not the final size.

## Pinning procedure

```sh
# 1. Pull the base model once, then resolve it to a digest:
ollama pull qwen3:8b
ollama show qwen3:8b --modelfile   # note the resolved digest

# 2. Replace the FROM line's tag with the digest, e.g.:
#    FROM qwen3@sha256:<digest>

# 3. Build the pinned, named model:
ollama create tradegraph-tier-fast -f ops/ollama/tier-fast.Modelfile

# 4. Point OLLAMA_MODEL_* env vars (.env.example) at the pinned name,
#    e.g. OLLAMA_MODEL_PLANNER=tradegraph-tier-fast
```

Re-run this whenever a tier's base model changes — that change is a 🎛️
tunable event (a new experiment, benchmarked against the frozen suite), not
a silent swap.

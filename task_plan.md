# Task Plan: PCV-MIA Cleanup

## Current Scope

Keep the repository focused on the PCV-MIA pipeline:

1. Preprocess and split datasets.
2. Build the KB_Member RAG index.
3. Optionally build Spoofed_Non_Member controls.
4. Build the immutable attack benchmark.
5. Extract facts, generate paired claims and paired queries.
6. Run RAG and LLM-only generation with OpenAI-compatible APIs.
7. Parse stances, compute PCV scores, baselines, defenses, and reports.

## Completed

- Removed old compatibility scripts and modules that were not part of the PCV-MIA flow.
- Removed offline/local profile support.
- Moved API key, base_url, and model switching into `.env`.

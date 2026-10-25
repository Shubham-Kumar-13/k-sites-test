---
title: K-Sites Backend
emoji: 🧬
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# K-Sites analysis backend

API-only backend for the K-Sites website (safe gene selection for knockout studies).
It has no web pages of its own; open the K-Sites website instead.

Configure it under **Settings → Variables and secrets**:

| Name | Type | Value |
|---|---|---|
| `KSITES_ACCESS_TOKEN` | Secret | The lab access code members type on the sign-in page |
| `KSITES_ALLOWED_ORIGINS` | Variable | The website address, e.g. `https://your-name.github.io` (no path, no trailing slash) |
| `K_SITES_NCBI_EMAIL` | Variable | A real email address (NCBI asks for one) |
| `NCBI_API_KEY` | Secret (optional) | NCBI key for higher PubMed rate limits |
| `KSITES_MAX_PARALLEL_JOBS` | Variable (optional) | Analyses run at once (default 2) |

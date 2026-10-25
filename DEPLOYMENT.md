# Hosting K-Sites for the lab (free, GitHub Pages only)

The website runs the **whole analysis inside each visitor's browser**. GitHub Pages only hands out
the page; the browser itself queries QuickGO, UniProt, NCBI, KEGG and PubMed, scores the genes, and
(optionally) predicts phenotypes with a small language model downloaded once (about 90 MB).
There is no server to pay for, sign in to, or keep awake.

```
GitHub Pages (static files) ──► your browser ──► QuickGO · UniProt · NCBI · PubMed · KEGG data files
```

What this means in practice:

- **Keep the tab open** while a job runs. Closing it pauses the job; opening the results page again
  resumes it (finished steps are remembered).
- **Jobs and results are stored in that browser only** (IndexedDB). Other computers do not see them
  and clearing site data removes them. Download the files you want to keep.
- **Phenotype prediction** downloads the model on first use (about 90 MB, cached afterwards) and then
  runs on the visitor's computer. It is a literature keyword heuristic, not a trained predictor:
  on 23 known mouse knockouts it called 10 of 11 lethal genes lethal and 11 of 12 viable genes
  not lethal (see `tools/evaluate_phenotype_prediction.py`). Treat it as a prompt to read the papers.
- **An NCBI API key is optional** (field on the analysis form). Without it the browser stays under
  NCBI's 3 requests/second limit; with it, 10/second.
- **KEGG pathway counts** come from data files built by the workflow (`kegg-data/`), refreshed monthly.
  KEGG data is free for academic use; the attribution is kept on the site.

## One-time setup

1. Push this repository to GitHub (for example `Shubham-Kumar-13/k-sites-test`) and make sure the
   default branch is `main` (or `master`).
2. In the repository: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Open the **Actions** tab, choose **Deploy the K-Sites website to GitHub Pages**, and press
   **Run workflow** (or just push a change under `webapp/`).
4. When it finishes the site is at `https://<user>.github.io/<repository>/`.

The workflow rebuilds the site whenever the pages change and on the 1st of each month (to refresh the
KEGG data).

## Building it yourself

```bash
pip install jinja2 requests
python tools/build_static_site.py --out site
python tools/build_kegg_data.py --out site/kegg-data
python -m http.server 8001 --directory site      # open http://127.0.0.1:8001/index.html
```

## Tests

```bash
python -m pytest tests                      # Python tests
cd tests/js && npm install && node --test *.test.mjs   # browser engine, compared with Python on recorded live data
```

## Troubleshooting

| Problem | Cause |
|---|---|
| Organism list is empty | `kegg-data/organisms.json` was not built; run `tools/build_kegg_data.py` |
| "Only X% of annotations were read" warning | The 2000-annotation safety limit was hit for a very large GO term |
| Jobs fail with NCBI errors | Rate limit; add an NCBI API key on the form and retry |
| Phenotype model does not load | Needs access to `cdn.jsdelivr.net` and `huggingface.co`; try another network |
| Job "paused" after closing the tab | Open the results page again to resume it |

## Optional: a separate Python backend

`python tools/build_static_site.py --api-base https://YOUR-BACKEND --out site` builds the older variant
whose pages call a hosted copy of `webapp/app.py` protected by an access code
(`KSITES_ACCESS_TOKEN`; see `deploy/huggingface/`). It is not needed for the browser version, and
Hugging Face Docker Spaces are no longer free.

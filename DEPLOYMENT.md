# Hosting K-Sites for the lab (free, GitHub Pages only)

The website runs the **whole analysis inside each visitor's browser**. GitHub Pages only hands out
the page; the browser itself queries QuickGO, UniProt, NCBI and PubMed, reads the knockout data files
that are published next to the pages, scores the genes, and (optionally) predicts phenotypes with a small
language model downloaded once (about 90 MB). There is no server to pay for, sign in to, or keep awake.

```
GitHub Pages (static files) ──► your browser ──► QuickGO · UniProt · NCBI · PubMed
        │                            ▲
        ├─ kegg-data/      pathway counts (KEGG)
        └─ evidence-data/  measured knockout evidence (MGI, IMPC, DepMap, gnomAD, GTEx, SGD, ZFIN, FlyBase, WormBase, Alliance, Ensembl)
```

What this means in practice:

- **Keep the tab open** while a job runs. Closing it pauses the job; opening the results page again
  resumes it (finished steps are remembered).
- **Jobs and results are stored in that browser only** (IndexedDB). Other computers do not see them
  and clearing site data removes them. Download the files you want to keep.
- **Measured knockout evidence** (`evidence-data/`) is what the verdicts rest on. The files are built by the
  workflow from public resources and refreshed monthly; the browser downloads only the file of the organism
  that is analysed (1 to 5 MB). `VALIDATION.md` shows how the data were checked against published knockouts.
- **Lethality estimate.** A gene with no knockout result gets an estimate of the chance that its knockout is lethal in mice,
  computed at build time from the human ortholog's DepMap, gnomAD and GTEx data by a small model that is tested on
  genes with known outcomes (cross-validated AUC 0.84, see `VALIDATION.md`). It is stored in the data files (field `pl`),
  so nothing is computed in the browser.
- **Phenotype prediction** is an experimental fallback for genes without a measured result or an estimate. It downloads the
  model on first use (about 90 MB, cached afterwards) and then runs on the visitor's computer. It is a
  literature keyword heuristic, not a trained predictor: on a random sample of 60 mouse genes it recognised
  7 of 30 lethal genes and wrongly flagged 4 of 30 viable ones (see `VALIDATION.md`). When every gene of a
  run has a measured result or an estimate, the model is never downloaded.
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
KEGG and knockout data). The first build downloads about 280 MB of source data and takes about 10 minutes (the paralog query alone about 5);
the downloads are cached for the month.

**What a build could not read.** Every build writes the sources it could not download into `build_warnings` in
`evidence-data/index.json` and leaves them out of the "Data sources" list. At the time of writing WormBase's download server
(`downloads.wormbase.org`) answers GitHub's build servers with HTTP 403 although it answers other networks, so the monthly
build has no measured worm data and worm genes carry only the mouse-ortholog hint; a build on another machine
(`python tools/build_evidence_data.py`) includes them. Zebrafish, fly and every other source were read.

**Data licences.** Please keep the attribution that the site and every report show. Checked against the providers'
own pages: MGI, IMPC, DepMap 24Q4 and SGD are CC BY 4.0; ZFIN states that its data and annotations are CC BY 4.0; FlyBase
states that its annotations and data are CC BY 4.0; WormBase describes itself as open access under a Creative Commons public
domain licence (its NAR 2020 and Genetics 2022 papers; its own policy page sits behind a bot check and could not be read by a
script, so please read https://wormbase.org/about/policies before you redistribute the files); HGNC is CC0; the Alliance of Genome Resources is CC0 1.0 for
most data and CC BY 4.0 for some (see its terms of use); Ensembl states that it puts no limits on the use of its data.
Not yet confirmed, because the providers' licence pages could not be read automatically: gnomAD (a free public
dataset; read the terms linked from https://gnomad.broadinstitute.org/downloads) and GTEx (read
https://gtexportal.org/home/license). Please read both before you redistribute the files outside this site.

**Sources that were looked at and not used.** Arabidopsis (and every other plant) still has no measured data. The embryo-defective
(EMB) gene set of the Meinke laboratory is published in a review whose supplementary tables are not open access (it is not in
PubMed Central), the SeedGenes web archive states no licence and its query functions have been switched off, and the bulk data of
TAIR (Phoenix Bioinformatics) are subject to terms that restrict redistributing substantial subsets (only the files in its
Public_Data_Releases folder are CC BY 4.0, and they hold no knockout phenotypes). Re-check them if one of them publishes an open
table. The community databases are optional in the build: if ZFIN, FlyBase or WormBase cannot be downloaded (WormBase's download host
sits behind a bot check that may block some servers), the build prints a warning and that organism keeps the mouse-ortholog hint.

## Building it yourself

```bash
pip install jinja2 requests
python tools/build_static_site.py --out site
python tools/build_kegg_data.py --out site/kegg-data
python tools/build_evidence_data.py --out site/evidence-data     # about 10 minutes the first time
python -m http.server 8001 --directory site      # open http://127.0.0.1:8001/index.html
```

## Tests

```bash
python -m pytest tests                      # Python tests
cd tests/js && npm install && node --test *.test.mjs   # browser engine, compared with Python on recorded live data
```

Every deploy also runs `tools/check_evidence_data.py` on the freshly built evidence: no verdict may break the rules in any organism
(for example a lethal gene rated Safe), at least 90% of the human core-essential genes must be rated Avoid in cultured cells, at least
95% of the non-essential genes must not be, and at least 85% of the mouse core-essential genes must be Avoid or High concern. The gold
lists are in `tools/data/gold/`. When the check fails, nothing is deployed and the site stays as it was; the build log shows why.

## Troubleshooting

| Problem | Cause |
|---|---|
| Organism list is empty | `kegg-data/organisms.json` was not built; run `tools/build_kegg_data.py` |
| Every gene says "Not verified" | `evidence-data/` is missing or unreadable; run `tools/build_evidence_data.py` (the results page says so in a warning) |
| "Only X% of annotations were read" warning | The 2000-annotation safety limit was hit for a very large GO term |
| Jobs fail with NCBI errors | Rate limit; add an NCBI API key on the form and retry |
| Phenotype model does not load | Needs access to `cdn.jsdelivr.net` and `huggingface.co`; try another network |
| Job "paused" after closing the tab | Open the results page again to resume it |

## Optional: a separate Python backend

`python tools/build_static_site.py --api-base https://YOUR-BACKEND --out site` builds the older variant
whose pages call a hosted copy of `webapp/app.py` protected by an access code
(`KSITES_ACCESS_TOKEN`; see `deploy/huggingface/`). It is not needed for the browser version, and
Hugging Face Docker Spaces are no longer free.

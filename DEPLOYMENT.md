# Hosting K-Sites for the lab

K-Sites runs in two parts:

| Part | What it is | Where it lives | Cost |
|---|---|---|---|
| **Website** | The pages lab members click through (forms, results, help) | GitHub Pages | free |
| **Analysis backend** | The Python code that queries QuickGO, UniProt, KEGG and PubMed and scores the genes | A Hugging Face Space (free CPU, 16 GB RAM) | free |

GitHub Pages can only serve static pages, so the analysis cannot run on GitHub itself. The website
asks the backend to do the work and shows the answer. Nothing in the analysis is simplified: the
same Python code, the same databases, phenotype prediction included.

```
lab member's browser ──► GitHub Pages (website)
                    └──► Hugging Face Space (analysis API) ──► QuickGO · UniProt · KEGG · PubMed
```

Who can use it: anyone who knows the **lab access code** you choose in step 2. The website itself is
public (GitHub Pages sites are), but it contains no data and does nothing without the code.

---

## What you need

- A GitHub account that owns this repository
- A free [Hugging Face](https://huggingface.co/join) account
- A real email address for NCBI (PubMed asks for one)
- A lab access code of your choice (a long phrase; share it only with lab members)

---

## Step 1: Create the backend on Hugging Face

1. Go to <https://huggingface.co/new-space>.
2. Name it, for example `k-sites-backend`. Choose **Docker** as the SDK, **Blank** template, **CPU basic (free)**.
   Visibility can be **Public** or **Private**; the access code protects the analysis either way.
3. Put the backend files in it. Either way works:
   - **By hand:** run `python tools/build_hf_space.py --out hf_space`, then upload everything inside the
     `hf_space` folder to the Space (Files tab → Add file → Upload files), or `git push` that folder to the Space's repository.
   - **Automatically from GitHub:** see "Keeping the backend up to date" below.
4. Wait for the build (about 10 minutes the first time; it downloads PyTorch and the embedding model).
   The Space shows **Running** when it is ready.
5. Note the backend address. It looks like `https://YOUR-HF-NAME-k-sites-backend.hf.space`
   (Space page → ⋯ menu → **Embed this Space** shows it).

## Step 2: Tell the backend its settings

In the Space: **Settings → Variables and secrets**.

| Name | Type | Value |
|---|---|---|
| `KSITES_ACCESS_TOKEN` | **Secret** | your lab access code |
| `KSITES_ALLOWED_ORIGINS` | Variable | `https://YOUR-GITHUB-NAME.github.io` (no path, no trailing slash) |
| `K_SITES_NCBI_EMAIL` | Variable | a real email address |
| `NCBI_API_KEY` | Secret (optional) | a free NCBI key, for higher PubMed limits |
| `KSITES_MAX_PARALLEL_JOBS` | Variable (optional) | analyses run at the same time (default 2) |

The Space restarts after you save. Check it: opening `https://…hf.space/api/health` should show `{"status":"ok","hosted":true,…}`.

## Step 3: Publish the website on GitHub Pages

1. In the GitHub repository: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. **Settings → Secrets and variables → Actions → Variables → New repository variable**:
   - Name `KSITES_API_BASE`
   - Value: the backend address from step 1 (no trailing slash)
3. **Actions** tab → **Deploy the K-Sites website to GitHub Pages** → **Run workflow**.
4. When it finishes, the website is at `https://YOUR-GITHUB-NAME.github.io/REPOSITORY-NAME/`.

Open it, enter the lab access code, your name and email, and run a small analysis to test.

---

## Using it

- **First visit after a quiet spell is slow.** Free Spaces go to sleep when idle. The sign-in page wakes the
  backend and says so; it usually takes one to two minutes.
- **Jobs run in the background.** You can close the page and come back through **Job History**.
- **Download your results.** The backend's disk is temporary: if the Space restarts or is rebuilt, saved
  jobs are lost. Download the HTML report, CSV or Excel files you need.
- **Two analyses at a time.** More are queued ("Waiting for a free analysis slot") so the public databases
  are not hammered.
- **Large GO terms are slow.** Every gene of the GO term is scored (several database calls each), so a term
  with 200 genes can take 20 minutes or more.

## Keeping the backend up to date from GitHub (optional)

So that a push to this repository also updates the Space:

1. In Hugging Face: **Settings → Access Tokens → New token** with **write** access.
2. In GitHub: **Settings → Secrets and variables → Actions**
   - Secret `HF_TOKEN` = that token
   - Variable `HF_SPACE` = `YOUR-HF-NAME/k-sites-backend`
3. The workflow **Update the K-Sites backend on Hugging Face** then runs on pushes that change the analysis code.

## Changing the access code

Change the `KSITES_ACCESS_TOKEN` secret in the Space. Everyone has to sign in again with the new code.

## Running everything on your own computer instead

No hosting needed:

```bash
pip install -e '.[all]'
python webapp/app.py          # http://127.0.0.1:5000  (name + email sign-in, no access code)
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Sign-in says "access code was not accepted" | Wrong code, or `KSITES_ACCESS_TOKEN` not set in the Space |
| Sign-in page stays on "Waking up the analysis server" | Space is still building or sleeping; check its page for **Running** |
| Browser console shows a CORS error | `KSITES_ALLOWED_ORIGINS` does not exactly match the website's address (check `https`, no trailing slash) |
| Website workflow fails with "Set the repository variable KSITES_API_BASE" | Step 3.2 not done |
| Job fails with "The server restarted while this job was running" | The Space restarted during the job; submit it again |
| Many genes listed as "not scored (insufficient data)" | A database was unreachable; the report says which. Run again later |

## Rebuilding the pieces by hand

```bash
python tools/build_static_site.py --api-base https://YOUR-SPACE.hf.space --out site   # the website
python tools/build_hf_space.py --out hf_space                                         # the backend folder
```

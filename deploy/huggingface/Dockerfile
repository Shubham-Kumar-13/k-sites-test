# K-Sites analysis backend for a Hugging Face Space (Docker SDK).
# Serves only the JSON API; the website itself lives on GitHub Pages.
FROM python:3.12-slim

# Hugging Face runs Spaces as user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONPATH=/home/user/app \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface \
    KSITES_DATA_DIR=/tmp/ksites \
    PORT=7860

WORKDIR /home/user/app

# CPU-only PyTorch first: the default wheel bundles CUDA and is several GB
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the phenotype-prediction embedding model at build time so the first job is not slow
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY --chown=user k_sites ./k_sites
COPY --chown=user webapp ./webapp

EXPOSE 7860

# One worker: analysis jobs run in threads of this process and share one job queue.
# The long timeout covers a slow first request while the model loads.
CMD ["gunicorn", "--chdir", "webapp", "--bind", "0.0.0.0:7860", "--workers", "1", "--threads", "8", "--timeout", "600", "app:app"]

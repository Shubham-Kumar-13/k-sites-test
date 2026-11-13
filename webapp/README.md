# K-Sites Web Application

A web interface for K-Sites, a tool that helps scientists pick a safe gene for knockout/deletion.

**Tagline:** Suite for Knock-out/down Studies

## Two ways to run it

- **Locally:** `python webapp/app.py` serves pages and API together (name + email sign-in).
- **Hosted:** set `KSITES_ACCESS_TOKEN` and the app becomes an API-only backend that the static website
  (built by `tools/build_static_site.py`) talks to. Settings: `KSITES_ACCESS_TOKEN`, `KSITES_ALLOWED_ORIGINS`,
  `KSITES_DATA_DIR`, `KSITES_MAX_PARALLEL_JOBS`, `PORT`. See [DEPLOYMENT.md](../DEPLOYMENT.md).

## Features

### 🧬 Hierarchical Organism Selection
1. **Select Kingdom**: Choose from Animals, Plants, Microbes, Fungi, or Other Eukaryotes
2. **Filter Species**: Type to filter or scroll through available species
3. **Direct Selection**: Click to select desired organism

### 🧪 Hierarchical GO Term Selection
1. **Select Category**: Biological Process, Molecular Function, or Cellular Component
2. **Filter Terms**: Search by keyword within category
3. **Direct Entry**: Option to enter GO:XXXXXXX ID directly

### 📊 Advanced Analysis Features
- **Multi-Database Evidence**: GO (QuickGO), UniProt data per gene; PubMed is used only when RAG phenotype prediction is enabled
- **RAG Phenotype Prediction**: AI-powered literature-based phenotype prediction
- **Smart Gene Limiting**: Real-time gene count validation with suggestions

### 📈 Enhanced Progress Tracking
- **Visual Progress Bar**: Shows exact percentage completion
- **Step-by-Step Status**: See which analysis step is currently running
- **ETA Calculation**: Estimated time of completion based on parameters

### 📚 Comprehensive Documentation
- **Help Page**: Detailed explanations of all analytical terms
- **Methodology Guide**: Step-by-step explanation of the pipeline
- **FAQ Section**: Common questions and answers
- **Score Explanations**: Pleiotropy, specificity, safety level, etc.

## Installation

### Prerequisites
- Python 3.8+
- K-Sites package installed (`pip install -e ..` from parent directory)

### Setup

1. Install webapp dependencies:
```bash
cd /home/iiab/Documents/K-sites/webapp
pip install -r requirements.txt
```

2. Configure environment variables:
```bash
# Required
export K_SITES_NCBI_EMAIL="your-email@example.com"
```

3. Start the server:
```bash
./start_server.sh
```

4. Open browser: http://localhost:5000

## Usage Workflow

### Starting an Analysis

1. **Select Organism**:
   - Click kingdom (e.g., "Animals")
   - Filter/scroll to find species (e.g., "Mus musculus")
   - Click to select
2. **Select GO Term**:
   - Click category (e.g., "Biological Process")
   - Filter to find term (e.g., "DNA repair")
   - Or enter GO:0006281 directly
3. **Choose Databases**: QuickGO is always used; add UniProt as needed
4. **Set Parameters**:
   - Max genes: 10-50 (lower = faster)
   - Max pleiotropy: 0-10 cutoff on the pleiotropy score (lower = only more specific genes)
   - Enable RAG prediction (optional, adds ~1 min/gene)
5. **Review Gene Count**: See available genes and estimated time
6. **Start Analysis**: Submit and wait for completion
7. **View Results**: Interactive dashboard with safety levels for every gene

### Understanding Results

Visit `/help` for detailed explanations of:
- **Pleiotropy Score**: Gene specificity (0=highly specific)
- **Specificity Score**: Inverse of pleiotropy on a 0-1 scale (1=highly specific)
- **Safety Level**: Overall risk assessment

## API Endpoints

### Hierarchical Selection
- `GET /api/organisms/kingdoms` - List organism kingdoms
- `GET /api/organisms/by-kingdom?kingdom=X&q=Y` - Get species in kingdom
- `GET /api/go-terms/categories` - List GO categories
- `GET /api/go-terms/by-category?category=X&q=Y` - Get terms in category

### Analysis
- `GET /api/evidence/coverage?taxid=X` - Whether measured knockout data exist for an organism
- `POST /api/analyze/validate` - Validate parameters with gene count
- `POST /api/analyze/start` - Start new job (returns job_id); `knockout_context` (`auto`, `cells`, `organism`) chooses
  whether the verdict follows cell-line screens or the knockout organism
- `GET /api/jobs/{id}/status` - Get job status with progress
- `GET /api/jobs/{id}/results` - Get completed results
- `GET /api/jobs/{id}/download/{format}` - Download HTML/JSON

## Architecture

```
webapp/
├── app.py                 # Flask application
├── config.py             # Configuration classes
├── requirements.txt      # Dependencies
├── start_server.sh      # Startup script
├── utils/
│   ├── hierarchical_data.py  # Organism/GO hierarchies
│   └── help_content.py       # Documentation content
├── static/js/
│   ├── main.js          # Main page JS
│   └── results.js       # Results page JS
├── templates/
│   ├── base.html        # Base layout
│   ├── index.html       # Analysis form
│   ├── results.html     # Results display
│   ├── jobs.html        # Job history
│   └── help.html        # Documentation
└── results/             # Analysis outputs
```

## Database Schema

### AnalysisJob Table
Tracks all analysis jobs with:
- Job ID, status, timestamps
- Current step and progress percentage
- Estimated completion time
- Optional user email (metadata only)
- All input parameters
- Results summary
- Error messages

## Troubleshooting

### No genes found
- Try a broader GO term
- Verify organism has GO annotations
- Check evidence filter settings

### Analysis timeout
- Reduce max_genes parameter
- Disable phenotype prediction
- Check database connectivity

## License

Same as K-Sites project (MIT License)

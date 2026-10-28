# PyPI Upload Guide for K-Sites

## Package Information

**Package Name**: `k-sites`  
**Current Version**: 1.1.0  
**Description**: K-Sites: A Non-Pleiotropic Gene Selection Platform for Knockout Studies

## What's New in v1.1.0

### Major Features
- **Non-Pleiotropic Gene Identification**: Multi-database integration (GO, UniProt, KEGG)
- **RAG-Based Phenotype Prediction**: Literature mining with semantic search
- **Web Application**: Flask-based UI with hierarchical selection
- **Email Notifications**: Analysis completion alerts
- **Multiple Export Formats**: CSV, Excel, HTML

### Installation Options

```bash
# Basic installation
pip install k-sites

# With RAG phenotype prediction support
pip install 'k-sites[rag]'

# With web application support
pip install 'k-sites[webapp]'

# With all features
pip install 'k-sites[all]'
```

## Upload Instructions

### Option 1: Automated Release Script (Recommended)

1. **Set your PyPI API token:**
   ```bash
   export PYPI_API_TOKEN='pypi-YourTokenHere'
   ```

2. **(Optional) Set your GitHub token:**
   ```bash
   export GITHUB_TOKEN='ghp_YourTokenHere'
   ```

3. **Run the release script:**
   ```bash
   chmod +x complete_release.sh
   ./complete_release.sh
   ```

### Option 2: Manual Upload

1. **Install build tools:**
   ```bash
   pip install twine build
   ```

2. **Build the package:**
   ```bash
   python -m build
   ```

3. **Verify the distribution:**
   ```bash
   twine check dist/*
   ```

4. **Upload to PyPI:**
   ```bash
   twine upload dist/*
   ```

   Enter your PyPI username (`__token__`) and API token as the password.

### Creating GitHub Repository Manually

If you prefer to create the GitHub repository manually:

1. Go to https://github.com/new
2. Repository name: `k-sites`
3. Description: `Non-Pleiotropic Gene Selection Platform for Knockout Studies`
4. Make it Public
5. Click "Create repository"
6. Follow the instructions to push an existing repository:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/k-sites.git
   git branch -M master
   git push -u origin master
   ```

## Post-Upload Verification

1. **Check the PyPI page:**
   - Visit: https://pypi.org/project/k-sites/
   - Verify version, description, and metadata

2. **Test installation:**
   ```bash
   pip install k-sites
   k-sites --help
   ```

3. **Test with all features:**
   ```bash
   pip install 'k-sites[all]'
   python -c "from k_sites.rag_system import RAGPhenotypePredictor; print('RAG system loaded')"
   ```

## Developers

- Kanaka KK (Lead Architect)
- Sandip Garai (Data Integration)
- Jeevan C (Algorithm Developer)
- Tanzil Fatima (Bioinformatics Analyst)

## License

MIT License - See LICENSE file for details.

## Support

- Issues: https://github.com/KanakaKK/K-sites/issues
- Documentation: https://github.com/KanakaKK/K-sites/blob/main/README.md

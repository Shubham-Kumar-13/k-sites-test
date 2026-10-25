#!/bin/bash
# Complete Release Script for K-Sites v1.1.0
# This script uploads the package to PyPI and creates a GitHub repository

set -e  # Exit on error

echo "=========================================="
echo "K-Sites v1.1.0 Release Script"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if PYPI_API_TOKEN is set
if [ -z "$PYPI_API_TOKEN" ]; then
    echo -e "${RED}Error: PYPI_API_TOKEN environment variable is not set${NC}"
    echo ""
    echo "To upload to PyPI, you need an API token:"
    echo "1. Go to https://pypi.org/manage/account/token/"
    echo "2. Create a new API token"
    echo "3. Set it as an environment variable:"
    echo "   export PYPI_API_TOKEN='pypi-...'"
    echo ""
    exit 1
fi

# Check if GITHUB_TOKEN is set
if [ -z "$GITHUB_TOKEN" ]; then
    echo -e "${YELLOW}Warning: GITHUB_TOKEN not set. GitHub repository creation will be skipped.${NC}"
    echo "To create a GitHub repository automatically:"
    echo "1. Go to https://github.com/settings/tokens"
    echo "2. Create a token with 'repo' scope"
    echo "3. Set it as an environment variable:"
    echo "   export GITHUB_TOKEN='ghp_...'"
    echo ""
fi

echo -e "${GREEN}Step 1: Verifying package...${NC}"
twine check dist/*

echo ""
echo -e "${GREEN}Step 2: Uploading to PyPI...${NC}"
echo "This will upload k-sites v1.1.0 to PyPI"
read -p "Are you sure you want to upload? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Upload cancelled."
    exit 0
fi

# Upload to PyPI
twine upload dist/* -u __token__ -p "$PYPI_API_TOKEN"

echo ""
echo -e "${GREEN}✓ Package uploaded to PyPI successfully!${NC}"
echo "  View at: https://pypi.org/project/k-sites/"

# GitHub repository creation
if [ -n "$GITHUB_TOKEN" ]; then
    echo ""
    echo -e "${GREEN}Step 3: Creating GitHub repository...${NC}"
    
    # Get GitHub username
    GITHUB_USER=$(curl -s -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | grep -o '"login": "[^"]*"' | cut -d'"' -f4)
    
    if [ -z "$GITHUB_USER" ]; then
        echo -e "${RED}Error: Could not get GitHub username from token${NC}"
        exit 1
    fi
    
    echo "Creating repository for user: $GITHUB_USER"
    
    # Create repository using GitHub API
    curl -s -X POST \
        -H "Authorization: token $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        https://api.github.com/user/repos \
        -d '{
            "name": "k-sites",
            "description": "Safe gene selection for knockout studies using GO, UniProt, KEGG and PubMed evidence",
            "homepage": "https://pypi.org/project/k-sites/",
            "private": false,
            "has_issues": true,
            "has_wiki": true,
            "has_downloads": true
        }'
    
    echo ""
    echo -e "${GREEN}✓ GitHub repository created!${NC}"
    echo "  URL: https://github.com/$GITHUB_USER/k-sites"
    
    # Add remote and push
    echo ""
    echo -e "${GREEN}Step 4: Pushing code to GitHub...${NC}"
    
    # Check if remote already exists
    if git remote get-url origin &>/dev/null; then
        git remote set-url origin "https://$GITHUB_TOKEN@github.com/$GITHUB_USER/k-sites.git"
    else
        git remote add origin "https://$GITHUB_TOKEN@github.com/$GITHUB_USER/k-sites.git"
    fi
    
    git push -u origin master
    
    echo ""
    echo -e "${GREEN}✓ Code pushed to GitHub successfully!${NC}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Release Complete!${NC}"
echo "=========================================="
echo ""
echo "Package: k-sites v1.1.0"
echo "PyPI: https://pypi.org/project/k-sites/"
if [ -n "$GITHUB_USER" ]; then
    echo "GitHub: https://github.com/$GITHUB_USER/k-sites"
fi
echo ""
echo "Installation:"
echo "  pip install k-sites"
echo ""
echo "With all features:"
echo "  pip install 'k-sites[all]'"
echo ""

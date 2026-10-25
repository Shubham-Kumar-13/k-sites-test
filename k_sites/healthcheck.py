"""
Self-diagnostic tool for Universal K-Sites workspace integrity.
Validates installation, dependencies, and external service connectivity.
"""

import os
import sys
import importlib.util
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any
import requests
from packaging import version


def check_filesystem_integrity() -> Tuple[bool, List[str]]:
    """Check filesystem integrity: required files and directories."""
    errors = []
    
    # Check main package structure
    k_sites_dir = Path("k_sites")
    if not k_sites_dir.exists():
        errors.append("k_sites directory not found")
        return False, errors
    
    # Check required files in main directory
    required_files = [
        "cli.py",
        "workflow/pipeline.py",
        "data_retrieval/organism_resolver.py",
        "data_retrieval/go_gene_mapper.py",
        "gene_analysis/pleiotropy_scorer.py",
        "workflow/safety_recommender.py",
        "rag_system/literature_context.py",
        "reporting/report_generator.py"
    ]
    
    for file_path in required_files:
        full_path = k_sites_dir / file_path
        if not full_path.exists():
            errors.append(f"Missing required file: {file_path}")
    
    # Check for __init__.py files in all subdirectories
    required_subdirs = [
        "k_sites/__init__.py",
        "k_sites/data_retrieval/__init__.py",
        "k_sites/gene_analysis/__init__.py",
        "k_sites/rag_system/__init__.py",
        "k_sites/workflow/__init__.py",
        "k_sites/reporting/__init__.py",
        "k_sites/config/__init__.py"
    ]
    
    for subdir_init in required_subdirs:
        if not Path(subdir_init).exists():
            errors.append(f"Missing __init__.py: {subdir_init}")
    
    # Check for example config
    if not Path("k-sites.yaml").exists():
        errors.append("Config template (k-sites.yaml) not found")
    
    return len(errors) == 0, errors


def check_python_imports() -> Tuple[bool, List[str]]:
    """Check that all modules import cleanly without circular dependencies."""
    errors = []
    
    # Change to the parent directory to make imports work
    original_cwd = os.getcwd()
    os.chdir(Path(__file__).parent.parent)
    
    try:
        # Test main import
        try:
            import k_sites
        except ImportError as e:
            errors.append(f"Failed to import k_sites: {e}")
            return False, errors
        
        # Test individual submodule imports
        modules_to_test = [
            "k_sites.cli",
            "k_sites.workflow",
            "k_sites.gene_analysis",
            "k_sites.rag_system",
            "k_sites.reporting",
            "k_sites.config"
        ]
        
        for module_name in modules_to_test:
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                errors.append(f"Failed to import {module_name}: {e}")
        
    finally:
        os.chdir(original_cwd)
    
    return len(errors) == 0, errors


def check_dependencies() -> Tuple[bool, List[str], Dict[str, str]]:
    """Check that required dependencies are installed with correct versions."""
    errors = []
    versions = {}
    
    # Test importing required packages
    required_packages = {
        "biopython": "Bio",
        "requests": "requests",
        "pyyaml": "yaml",
        "tqdm": "tqdm",
        "dataclasses_json": "dataclasses_json",
        "pandas": "pandas"
    }
    
    for pkg_name, import_name in required_packages.items():
        try:
            module = importlib.import_module(import_name)
            # Try to get version
            if hasattr(module, '__version__'):
                ver = module.__version__
            elif hasattr(module, '__VERSION__'):
                ver = module.__VERSION__
            else:
                ver = "unknown"
            
            versions[pkg_name] = str(ver)
        except ImportError:
            errors.append(f"Package {pkg_name} not installed")
    
    # Check version compatibility
    if "biopython" in versions:
        bio_ver = versions["biopython"]
        try:
            if version.parse(bio_ver) < version.parse("1.80"):
                errors.append(f"Biopython version {bio_ver} is too old, requires >= 1.80")
        except:
            errors.append(f"Could not parse Biopython version: {bio_ver}")
    
    return len(errors) == 0, errors, versions


def check_external_services() -> Dict[str, Any]:
    """Check reachability of external services (non-blocking)."""
    results = {}
    
    # Check NCBI E-Utils
    try:
        response = requests.head(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
            timeout=5
        )
        results["ncbi"] = {
            "reachable": response.status_code < 500,
            "status_code": response.status_code
        }
    except Exception as e:
        results["ncbi"] = {
            "reachable": False,
            "error": str(e)
        }
    
    # Check QuickGO
    try:
        response = requests.head(
            "https://www.ebi.ac.uk/QuickGO/services/",
            timeout=5
        )
        results["quickgo"] = {
            "reachable": response.status_code < 500,
            "status_code": response.status_code
        }
    except Exception as e:
        results["quickgo"] = {
            "reachable": False,
            "error": str(e)
        }
    
    return results


def check_configuration() -> Tuple[bool, List[str], Dict[str, Any]]:
    """Check configuration readiness."""
    errors = []
    warnings = []
    config_info = {}
    
    # Check NCBI email
    ncbi_email = os.getenv("NCBI_EMAIL") or os.getenv("K_SITES_NCBI_EMAIL")
    if not ncbi_email or ncbi_email == "user@example.com":
        errors.append("NCBI_EMAIL not set in environment or config - required for NCBI E-Utils")
        config_info["ncbi_email_set"] = False
    else:
        config_info["ncbi_email_set"] = True
    
    return len(errors) == 0, warnings, config_info


def run_health_check() -> None:
    """Run complete health check and display results."""
    print("K-Sites Health Check")
    print("────────────────")
    
    # 1. Filesystem integrity
    fs_ok, fs_errors = check_filesystem_integrity()
    if fs_ok:
        print("✅ Filesystem: All required files present")
    else:
        print("❌ Filesystem: Issues found")
        for error in fs_errors:
            print(f"   - {error}")
    
    # 2. Python imports
    import_ok, import_errors = check_python_imports()
    if import_ok:
        print("✅ Python imports: Clean (0 errors)")
    else:
        print("❌ Python imports: Issues found")
        for error in import_errors:
            print(f"   - {error}")
    
    # 3. Dependencies
    deps_ok, dep_errors, versions = check_dependencies()
    if deps_ok:
        version_str = ", ".join([f"{k}={v}" for k, v in versions.items()])
        print(f"✅ Dependencies: {version_str}")
    else:
        print("❌ Dependencies: Issues found")
        for error in dep_errors:
            print(f"   - {error}")
    
    # 4. External services (warnings only)
    service_results = check_external_services()
    
    # NCBI
    if service_results["ncbi"]["reachable"]:
        print("✅ NCBI: Reachable")
    else:
        print(f"⚠️  NCBI: Not reachable ({service_results['ncbi'].get('error', 'connection failed')})")
    
    # QuickGO
    if service_results["quickgo"]["reachable"]:
        print("✅ QuickGO: Reachable")
    else:
        print(f"⚠️  QuickGO: Not reachable ({service_results['quickgo'].get('error', 'connection failed')})")
    
    # 5. Configuration
    config_ok, config_warnings, config_info = check_configuration()
    if config_ok:
        print("✅ Configuration: All required settings present")
    else:
        print("⚠️  Configuration: Some issues found")
        for warning in config_warnings:
            print(f"   - {warning}")
    
    # Determine overall status
    overall_status = "READY"
    if not fs_ok or not import_ok or not deps_ok:
        overall_status = "ISSUES DETECTED"
    
    print(f"Status: {overall_status}")


if __name__ == "__main__":
    run_health_check()
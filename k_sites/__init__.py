"""
K-Sites: Safe Gene Selection for Knockout

A tool that helps scientists pick a safe (low-pleiotropy) gene for deletion,
using GO, UniProt and PubMed evidence.
"""

__version__ = "1.2.1"
__author__ = "K-Sites Development Team"
__description__ = "Safe gene selection for knockout using GO, UniProt and PubMed evidence"

from k_sites.workflow.pipeline import run_k_sites_pipeline
from k_sites.cli import main

__all__ = [
    "run_k_sites_pipeline", 
    "main",
    "__version__"
]
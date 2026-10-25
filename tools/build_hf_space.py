#!/usr/bin/env python3
"""
Assemble the folder that is uploaded to the Hugging Face Space (the K-Sites backend).

    python tools/build_hf_space.py --out hf_space

The Space needs its own flat repository: Dockerfile, README card and requirements at the
root, next to the k_sites/ package and the webapp/ API. Test data, caches and the local job
database are left out.
"""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy" / "huggingface"

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info", ".pytest_cache", "results", "*.db")


def build(out: Path) -> list:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in ("Dockerfile", "README.md", "requirements.txt"):
        shutil.copy2(DEPLOY / name, out / name)
    shutil.copytree(ROOT / "k_sites", out / "k_sites", ignore=IGNORE)
    shutil.copytree(ROOT / "webapp", out / "webapp", ignore=IGNORE)

    return sorted(str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*") if p.is_file())


def main():
    parser = argparse.ArgumentParser(description="Assemble the Hugging Face Space folder for the K-Sites backend.")
    parser.add_argument("--out", default="hf_space", help="Output folder (default: hf_space)")
    args = parser.parse_args()

    files = build(Path(args.out))
    print(f"Assembled {len(files)} files in {Path(args.out).resolve()}")
    for name in files[:12]:
        print(f"  {name}")
    if len(files) > 12:
        print(f"  ... and {len(files) - 12} more")


if __name__ == "__main__":
    main()

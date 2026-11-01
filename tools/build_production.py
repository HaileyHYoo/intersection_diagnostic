"""Build the production package from the shared source.

    python tools/build_production.py           build production/ and check that it imports
    python tools/build_production.py --check   only verify that production/ matches the source

The production team copies production/dash_backend/ai_brains/intersections/diagnostics/ into the backend
(see production/PRODUCTION_UPDATE.md). Local-only modules (diagnostics/local: synthetic network, map viewer,
inspection) are left out. Do not edit production/ by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "diagnostics"
OUT = ROOT / "production"
TARGET = OUT / "dash_backend" / "ai_brains" / "intersections" / "diagnostics"
EXCLUDE_DIRS = {"local", "__pycache__"}
DOCS = {"docs/PRODUCTION_UPDATE.md": "PRODUCTION_UPDATE.md", "docs/METHOD.md": "METHOD.md",
        "docs/SCHEMA.md": "SCHEMA.md", "docs/DATA_MAPPING.md": "DATA_MAPPING.md", "requirements.txt": "requirements.txt", ".env.example": ".env.example"}


def source_files() -> list[Path]:
    return sorted(p for p in SOURCE.rglob("*") if p.is_file()
                  and not EXCLUDE_DIRS.intersection(p.relative_to(SOURCE).parts) and p.suffix != ".pyc")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> dict:
    return {"package": "dash_backend.ai_brains.intersections.diagnostics",
            "files": {str(p.relative_to(SOURCE)): digest(p) for p in source_files()}}


def check_imports() -> None:
    code = ("import sys; sys.path.insert(0, %r); "
            "import dash_backend.ai_brains.intersections.diagnostics.host as h; "
            "import dash_backend.ai_brains.intersections.diagnostics.templates as t; "
            "assert set(t.catalog()) == {'D001', 'D002'}; "
            "import dash_backend.ai_brains.intersections.diagnostics.contract.core as c; print('import ok')") % str(OUT)
    subprocess.run([sys.executable, "-I", "-c", code], check=True, cwd=OUT)
    leaked = [p for p in TARGET.rglob("*.py") if "from .local" in p.read_text() or "from ..local" in p.read_text()]
    if leaked:
        raise SystemExit(f"Production code imports local-only modules: {leaked}")


def build() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    for path in source_files():
        dest = TARGET / path.relative_to(SOURCE)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    for src, dst in DOCS.items():
        if (ROOT / src).exists():
            shutil.copy2(ROOT / src, OUT / dst)
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest(), indent=2) + "\n", encoding="utf-8")
    check_imports()
    print(f"Built {len(source_files())} files into {TARGET.relative_to(ROOT)}")


def check() -> int:
    saved = json.loads((OUT / "MANIFEST.json").read_text(encoding="utf-8"))
    if saved != manifest():
        print("production/ is out of date: run python tools/build_production.py")
        return 1
    built = {str(p.relative_to(TARGET)): digest(p) for p in TARGET.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    if built != saved["files"]:
        print("production/ was edited by hand or is incomplete: rebuild it")
        return 1
    print("production/ matches the source")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    sys.exit(check() if args.check else build() or 0)

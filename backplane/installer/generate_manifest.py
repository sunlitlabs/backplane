"""Regenerates a release manifest.json by scanning the backplane package
for every .py file it contains.

Run this before cutting a release (after bumping __version__ in
backplane/__init__.py and tagging), then upload the resulting file as a
release asset named manifest.json -- a manual step, deliberately: shipping
a release is a considered action, not something that happens automatically
as a side effect of a commit (same convention this tool ecosystem already
follows elsewhere). The manifest itself is a build artifact, not source --
it isn't committed to the repo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backplane import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def build_manifest() -> dict:
    package_dir = REPO_ROOT / "backplane"
    files = sorted(
        str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        for p in package_dir.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    return {"version": __version__, "files": files}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    out_path = Path(argv[0]) if argv else REPO_ROOT / "manifest.json"

    manifest = build_manifest()
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} with {len(manifest['files'])} files at version {manifest['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

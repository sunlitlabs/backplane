"""Self-contained, stdlib-only bootstrap for a completely fresh machine.

The chicken-and-egg problem this solves: every other piece of Backplane's
launch logic (backplane.installer.launch_cli, real_actions.py, updater.py)
is itself part of the `backplane` package -- which doesn't exist anywhere
on a fresh machine yet. This script can't import any of that, so it
duplicates the minimal subset of fetch-latest-release + write-versioned-
folder + flip-junction logic needed to get Backplane's own code onto disk
for the very first time. Once that's done, it hands off to the real
package for everything else -- this script's job is over after one run;
every subsequent launch goes through the real, fully-featured
backplane.installer.launch_cli directly.

Deliberately dependency-free (stdlib only: urllib, json, subprocess) --
the whole point is that it has to run *before* pip has installed anything
for this project.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

PUBLISHER = "Sunlit Labs"
APP_NAME = "Backplane"
REPO = "sunlitlabs/backplane"
GITHUB_API = "https://api.github.com"


def _backplane_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / PUBLISHER / APP_NAME


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Backplane-Bootstrap"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def _is_backplane_present(root: Path) -> bool:
    return (root / "current" / "backplane" / "__init__.py").exists()


def _fetch_and_install_backplane(root: Path) -> None:
    release = json.loads(_http_get(f"{GITHUB_API}/repos/{REPO}/releases/latest"))
    tag = release["tag_name"]
    manifest_asset = next((a for a in release.get("assets", []) if a["name"] == "manifest.json"), None)
    if manifest_asset is None:
        raise RuntimeError(f"Release {tag} has no manifest.json asset")
    manifest = json.loads(_http_get(manifest_asset["browser_download_url"]))

    version = tag.lstrip("v")
    version_dir = root / "versions" / version
    if version_dir.exists():
        raise RuntimeError(f"Version {version} already exists at {version_dir} but current/ isn't set up")
    version_dir.mkdir(parents=True)

    for rel_path in manifest["files"]:
        content = _http_get(f"https://raw.githubusercontent.com/{REPO}/{tag}/{rel_path}")
        dest = version_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    current_link = root / "current"
    if os.path.lexists(str(current_link)):
        os.rmdir(str(current_link))
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(current_link), str(version_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create junction: {result.stderr or result.stdout}")
    (root / "current_version.txt").write_text(version, encoding="utf-8")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print("usage: bootstrap_standalone.py <plugin-name> <plugin-repo>", file=sys.stderr)
        return 2
    plugin_name, plugin_repo = argv[0], argv[1]

    root = _backplane_root()
    if not _is_backplane_present(root):
        print("Backplane isn't installed yet -- fetching it for the first time...")
        _fetch_and_install_backplane(root)

    sys.path.insert(0, str(root / "current"))
    from backplane.installer.launch_cli import main as real_main  # noqa: E402 -- must import after sys.path insert

    return real_main([plugin_name, plugin_repo])


if __name__ == "__main__":
    sys.exit(main())

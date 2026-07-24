"""Update checking and application.

Trigger: GitHub Releases, compared by SemVer against a local version --
every Backplane-based repo uses the same scheme so this check is uniform
whether it's Backplane itself or a plugin. Application writes into a fresh
``versions/<version>/`` folder and flips a ``current`` directory junction
rather than overwriting files in place, so a process already running keeps
using whatever it loaded at its own startup, and rollback is just
re-pointing ``current`` back rather than restoring a file-by-file backup.

Network-touching functions (``fetch_latest_release``, ``fetch_release_
files``) take an injectable ``http_get`` so the rest of this module -- the
part that's actually novel to Backplane's own design -- can be tested
against real filesystem/junction behavior without depending on live
GitHub availability in every test run. The default transport
(``_default_http_get``) is exercised for real in tests/test_updater.py
against a local HTTP server instead.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

GITHUB_API = "https://api.github.com"

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

HttpGet = Callable[[str], bytes]


class UpdaterError(Exception):
    """Anything that stops an update check or application from
    completing -- a malformed tag, a missing manifest asset, an unreachable
    repo, or a filesystem/junction operation failing."""


def parse_semver(tag: str) -> Tuple[int, int, int]:
    match = _SEMVER_RE.match(tag.strip())
    if not match:
        raise UpdaterError(f"Not a valid vMAJOR.MINOR.PATCH tag: {tag!r}")
    return tuple(int(x) for x in match.groups())  # type: ignore[return-value]


def format_semver(version: Tuple[int, int, int]) -> str:
    return f"v{version[0]}.{version[1]}.{version[2]}"


def is_newer(candidate: Tuple[int, int, int], current: Optional[Tuple[int, int, int]]) -> bool:
    if current is None:
        return True
    return candidate > current


@dataclass
class ReleaseInfo:
    repo: str
    tag: str
    version: Tuple[int, int, int]
    manifest_url: str
    html_url: str


def fetch_latest_release(repo: str, http_get: Optional[HttpGet] = None) -> Optional[ReleaseInfo]:
    """``repo`` is 'owner/name'. Returns None if the repo has no releases
    at all (a fresh repo, or one that hasn't shipped v1 yet) rather than
    raising -- that's a normal state, not an error."""
    http_get = http_get or _default_http_get
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    try:
        raw = http_get(url)
    except _HttpNotFound:
        return None
    except UpdaterError:
        raise
    except Exception as exc:  # noqa: BLE001 -- normalized into UpdaterError for callers
        raise UpdaterError(f"Failed to reach GitHub for {repo}: {exc}") from exc

    data = json.loads(raw)
    tag = data["tag_name"]
    version = parse_semver(tag)
    manifest_asset = next((a for a in data.get("assets", []) if a["name"] == "manifest.json"), None)
    if manifest_asset is None:
        raise UpdaterError(f"Release {tag} for {repo} has no manifest.json asset")
    return ReleaseInfo(
        repo=repo,
        tag=tag,
        version=version,
        manifest_url=manifest_asset["browser_download_url"],
        html_url=data["html_url"],
    )


def fetch_manifest(release: ReleaseInfo, http_get: Optional[HttpGet] = None) -> Dict:
    http_get = http_get or _default_http_get
    return json.loads(http_get(release.manifest_url))


def fetch_release_files(
    repo: str, tag: str, file_paths: List[str], http_get: Optional[HttpGet] = None
) -> Dict[str, bytes]:
    """Downloads each listed file's raw content directly from the tagged
    ref -- a per-file manifest diff, not a full source archive, and never
    a git operation (updates must not assume git is available)."""
    http_get = http_get or _default_http_get
    return {rel_path: http_get(f"https://raw.githubusercontent.com/{repo}/{tag}/{rel_path}") for rel_path in file_paths}


class _HttpNotFound(Exception):
    """Raised by ``_default_http_get`` for a 404, translated to None by
    ``fetch_latest_release`` (no releases yet) rather than an error."""


def _default_http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Backplane-Updater"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise _HttpNotFound(url) from exc
        raise


class VersionedInstall:
    """Manages a ``versions/<version>/`` + ``current`` junction layout for
    one component (Backplane itself, or a single plugin).

    A directory junction, not a symlink: junctions don't require
    administrator rights or Developer Mode, unlike symlinks -- a real
    constraint for a per-user install with no elevation, not a style
    choice. Created/replaced by shelling out to ``mklink /J`` (Python's
    stdlib has no junction-creation API; ``os.symlink`` on Windows creates
    an actual symlink, a different reparse-point type with a real
    privilege requirement this design specifically avoids).

    The current version is also tracked in a plain ``current_version.txt``
    file rather than resolved by reading the junction back -- reparse-point
    resolution behavior has enough real-world inconsistency across Python/
    Windows versions that it isn't worth relying on for something this
    load-bearing when a plain text file is simpler and unambiguous.
    """

    def __init__(self, root: Path):
        self.root = root
        self.versions_dir = root / "versions"
        self.current_link = root / "current"
        self._current_version_file = root / "current_version.txt"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def installed_versions(self) -> List[str]:
        if not self.versions_dir.exists():
            return []
        names = [p.name for p in self.versions_dir.iterdir() if p.is_dir()]
        return sorted(names, key=lambda v: parse_semver(v) if _looks_like_semver(v) else (0, 0, 0))

    def current_version(self) -> Optional[str]:
        if not self._current_version_file.exists():
            return None
        version = self._current_version_file.read_text(encoding="utf-8").strip()
        return version or None

    def install_version(self, version: str, files: Dict[str, bytes]) -> Path:
        """Writes ``files`` (relative path -> content) into a fresh
        ``versions/<version>/`` folder. Does not flip ``current`` --
        callers decide when that happens (typically after the user
        confirms restart)."""
        version_dir = self.versions_dir / version
        if version_dir.exists():
            raise UpdaterError(f"Version {version!r} is already installed at {version_dir}")
        version_dir.mkdir(parents=True)
        for rel_path, content in files.items():
            dest = version_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        return version_dir

    def set_current(self, version: str) -> None:
        version_dir = self.versions_dir / version
        if not version_dir.is_dir():
            raise UpdaterError(f"Version {version!r} is not installed under {self.versions_dir}")
        _replace_junction(self.current_link, version_dir)
        self._current_version_file.write_text(version, encoding="utf-8")

    def mark_started_successfully(self, version: str) -> None:
        marker = self.versions_dir / version / ".started_ok"
        if (self.versions_dir / version).is_dir():
            marker.write_text("", encoding="utf-8")

    def has_started_successfully(self, version: str) -> bool:
        return (self.versions_dir / version / ".started_ok").exists()

    def prune(self) -> List[str]:
        """Removes every installed version except the current one and the
        version immediately before it in install order -- the one-step
        rollback target, per ARCHITECTURE.md.

        Only prunes at all once the *current* version has proven it
        starts successfully. Until then, everything is left alone: if
        current hasn't proven itself yet, its predecessor is exactly the
        version that might still be needed to roll back to, and removing
        it now -- before knowing whether current is actually good --
        would defeat the entire point of keeping a rollback target.
        Returns the versions actually removed."""
        current = self.current_version()
        if current is None or not self.has_started_successfully(current):
            return []

        versions = self.installed_versions()
        if current not in versions:
            return []

        current_index = versions.index(current)
        keep = {current}
        if current_index > 0:
            keep.add(versions[current_index - 1])

        removed = []
        for version in versions:
            if version not in keep:
                shutil.rmtree(self.versions_dir / version, ignore_errors=True)
                removed.append(version)
        return removed


def _looks_like_semver(name: str) -> bool:
    return bool(_SEMVER_RE.match(name))


def _replace_junction(link_path: Path, target_path: Path) -> None:
    if os.path.lexists(str(link_path)):
        # Removes just the reparse point/junction entry -- never the
        # target's contents. shutil.rmtree must never be used here: it
        # would walk into the target through the junction.
        os.rmdir(str(link_path))

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UpdaterError(
            f"Failed to create junction {link_path} -> {target_path}: {result.stderr or result.stdout}"
        )

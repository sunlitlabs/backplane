"""Tests for the updater: SemVer handling, the versioned-install/junction/
rollback/pruning mechanism (real filesystem, real junctions -- this is the
part that's actually novel to Backplane's design), and the GitHub-fetching
functions via dependency injection (an external network boundary, not
something to hit live in an automated suite -- see test_default_http_get
for the one test that exercises the real HTTP transport, against a local
server rather than live GitHub).
"""

from __future__ import annotations

import http.server
import json
import threading

import pytest

from backplane.host.updater import (
    ReleaseInfo,
    UpdaterError,
    VersionedInstall,
    _default_http_get,
    fetch_latest_release,
    fetch_manifest,
    fetch_release_files,
    format_semver,
    is_newer,
    parse_semver,
)

# -- SemVer -----------------------------------------------------------------


def test_parse_semver_with_v_prefix():
    assert parse_semver("v1.4.2") == (1, 4, 2)


def test_parse_semver_without_v_prefix():
    assert parse_semver("1.4.2") == (1, 4, 2)


def test_parse_semver_rejects_malformed_tag():
    with pytest.raises(UpdaterError):
        parse_semver("not-a-version")


def test_format_semver_round_trips():
    assert format_semver((1, 4, 2)) == "v1.4.2"


def test_is_newer_compares_correctly():
    assert is_newer((1, 1, 0), (1, 0, 0))
    assert not is_newer((1, 0, 0), (1, 0, 0))
    assert not is_newer((0, 9, 0), (1, 0, 0))


def test_is_newer_true_when_nothing_installed_yet():
    assert is_newer((1, 0, 0), None)


# -- VersionedInstall: the real junction mechanism ---------------------------


def test_install_version_writes_files_without_touching_current(tmp_path):
    install = VersionedInstall(tmp_path)
    install.install_version("1.0.0", {"app.py": b"print('v1')", "sub/mod.py": b"x = 1"})

    assert (tmp_path / "versions" / "1.0.0" / "app.py").read_bytes() == b"print('v1')"
    assert (tmp_path / "versions" / "1.0.0" / "sub" / "mod.py").read_bytes() == b"x = 1"
    assert install.current_version() is None  # set_current was never called


def test_set_current_creates_a_working_junction(tmp_path):
    install = VersionedInstall(tmp_path)
    install.install_version("1.0.0", {"app.py": b"print('v1')"})
    install.set_current("1.0.0")

    assert install.current_version() == "1.0.0"
    # Prove it's a real, working redirect, not just bookkeeping.
    assert (tmp_path / "current" / "app.py").read_bytes() == b"print('v1')"


def test_flipping_current_does_not_delete_the_previous_versions_files(tmp_path):
    install = VersionedInstall(tmp_path)
    install.install_version("1.0.0", {"app.py": b"print('v1')"})
    install.set_current("1.0.0")

    install.install_version("1.1.0", {"app.py": b"print('v2')"})
    install.set_current("1.1.0")

    assert (tmp_path / "current" / "app.py").read_bytes() == b"print('v2')"
    # The old version's actual files must survive the junction replacement --
    # this is the one thing that would be catastrophic to get wrong (rmtree
    # walking through the junction into the target).
    assert (tmp_path / "versions" / "1.0.0" / "app.py").read_bytes() == b"print('v1')"


def test_rollback_is_just_repointing_current_back(tmp_path):
    install = VersionedInstall(tmp_path)
    install.install_version("1.0.0", {"app.py": b"print('v1')"})
    install.set_current("1.0.0")
    install.install_version("1.1.0", {"app.py": b"print('v2')"})
    install.set_current("1.1.0")

    # Simulate "the new version failed to start" -> roll back.
    install.set_current("1.0.0")

    assert install.current_version() == "1.0.0"
    assert (tmp_path / "current" / "app.py").read_bytes() == b"print('v1')"
    # And rolling forward again still works -- 1.1.0's files were never touched.
    install.set_current("1.1.0")
    assert (tmp_path / "current" / "app.py").read_bytes() == b"print('v2')"


def test_install_version_raises_if_already_installed(tmp_path):
    install = VersionedInstall(tmp_path)
    install.install_version("1.0.0", {"app.py": b"v1"})
    with pytest.raises(UpdaterError):
        install.install_version("1.0.0", {"app.py": b"v1-again"})


def test_set_current_raises_for_an_uninstalled_version(tmp_path):
    install = VersionedInstall(tmp_path)
    with pytest.raises(UpdaterError):
        install.set_current("9.9.9")


def test_prune_keeps_only_current_and_immediately_previous(tmp_path):
    install = VersionedInstall(tmp_path)
    for v in ("1.0.0", "1.1.0", "1.2.0", "1.3.0"):
        install.install_version(v, {"app.py": v.encode()})
    install.set_current("1.3.0")
    # The trigger described in ARCHITECTURE.md: prune once the *new*
    # (current) version has proven it starts successfully.
    install.mark_started_successfully("1.3.0")

    removed = install.prune()

    # Keeps current (1.3.0) + the one immediately before it (1.2.0) only.
    assert set(removed) == {"1.0.0", "1.1.0"}
    assert set(install.installed_versions()) == {"1.2.0", "1.3.0"}


def test_prune_does_nothing_until_current_has_proven_itself(tmp_path):
    install = VersionedInstall(tmp_path)
    install.install_version("1.0.0", {"app.py": b"v1"})
    install.set_current("1.0.0")
    install.install_version("1.1.0", {"app.py": b"v2"})
    install.set_current("1.1.0")
    # 1.1.0 (current) never marked started -- e.g. it just crashed on
    # launch. 1.0.0 is exactly the rollback target that would be needed
    # in that case, so pruning must not touch it yet.

    removed = install.prune()

    assert removed == []
    assert set(install.installed_versions()) == {"1.0.0", "1.1.0"}


def test_prune_after_rollback_to_the_oldest_version_drops_the_failed_ones(tmp_path):
    install = VersionedInstall(tmp_path)
    for v in ("1.0.0", "1.1.0", "1.2.0"):
        install.install_version(v, {"app.py": v.encode()})
    install.set_current("1.0.0")
    install.mark_started_successfully("1.0.0")
    install.set_current("1.1.0")
    install.set_current("1.2.0")
    # 1.2.0 turned out bad and was never marked started -- roll back.
    install.set_current("1.0.0")

    removed = install.prune()

    # 1.0.0 is current and already proven, with nothing before it to keep
    # as a rollback target -- the untested/failed newer versions can go.
    assert set(removed) == {"1.1.0", "1.2.0"}
    assert set(install.installed_versions()) == {"1.0.0"}


# -- GitHub fetch functions, via dependency injection ------------------------


def test_fetch_latest_release_parses_a_well_formed_response():
    fake_response = json.dumps(
        {
            "tag_name": "v1.2.3",
            "html_url": "https://github.com/sunlitlabs/backplane/releases/tag/v1.2.3",
            "assets": [{"name": "manifest.json", "browser_download_url": "https://example.invalid/manifest.json"}],
        }
    ).encode("utf-8")

    release = fetch_latest_release("sunlitlabs/backplane", http_get=lambda url: fake_response)

    assert release.tag == "v1.2.3"
    assert release.version == (1, 2, 3)
    assert release.manifest_url == "https://example.invalid/manifest.json"


def test_fetch_latest_release_raises_if_manifest_asset_missing():
    fake_response = json.dumps({"tag_name": "v1.2.3", "html_url": "...", "assets": []}).encode("utf-8")
    with pytest.raises(UpdaterError):
        fetch_latest_release("sunlitlabs/backplane", http_get=lambda url: fake_response)


def test_fetch_manifest_parses_json():
    release = ReleaseInfo(repo="r", tag="v1.0.0", version=(1, 0, 0), manifest_url="u", html_url="h")
    manifest = fetch_manifest(release, http_get=lambda url: b'{"version": "1.0.0", "files": ["a.py"]}')
    assert manifest == {"version": "1.0.0", "files": ["a.py"]}


def test_fetch_release_files_downloads_each_listed_file():
    calls = []

    def fake_get(url):
        calls.append(url)
        return f"content of {url.rsplit('/', 1)[-1]}".encode()

    files = fetch_release_files("sunlitlabs/backplane", "v1.0.0", ["a.py", "sub/b.py"], http_get=fake_get)

    assert files["a.py"] == b"content of a.py"
    assert files["sub/b.py"] == b"content of b.py"
    assert all("sunlitlabs/backplane/v1.0.0" in url for url in calls)


# -- Real HTTP transport, against a local server (not live GitHub) ----------


def test_default_http_get_performs_a_real_http_request():
    """Exercises the actual urllib-based transport for real, against a
    local server rather than live GitHub -- proves the request/response
    plumbing itself works without depending on live internet/GitHub
    availability in this test suite."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"hello": "world"}')

        def log_message(self, *args):
            pass  # keep test output quiet

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        raw = _default_http_get(f"http://127.0.0.1:{port}/some/path")
        assert json.loads(raw) == {"hello": "world"}
    finally:
        server.shutdown()
        thread.join(timeout=5)

"""Tests for the real LauncherActions wiring -- real VersionedInstall/
PluginRegistry against a temp directory (the actual mechanism), with only
the GitHub network calls faked (an external boundary, same approach as
test_updater.py).
"""

from __future__ import annotations

import json

from backplane.installer import real_actions as ra
from backplane.host.updater import ReleaseInfo


def _fake_release(repo, tag="v1.0.0"):
    return ReleaseInfo(repo=repo, tag=tag, version=(1, 0, 0), manifest_url="https://example.invalid/manifest.json", html_url="h")


def test_install_component_installs_and_sets_current(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "fetch_latest_release", lambda repo: _fake_release(repo))
    monkeypatch.setattr(ra, "fetch_manifest", lambda release: {"version": "1.0.0", "files": ["plugin.json", "app.py"]})
    monkeypatch.setattr(
        ra,
        "fetch_release_files",
        lambda repo, tag, files: {"plugin.json": b'{"name": "x"}', "app.py": b"print('hi')"},
    )

    version = ra.install_component("owner/some-repo", tmp_path)

    assert version == "1.0.0"
    assert (tmp_path / "current" / "app.py").read_bytes() == b"print('hi')"
    assert (tmp_path / "current_version.txt").read_text(encoding="utf-8") == "1.0.0"


def test_build_real_actions_reflects_real_backplane_and_registry_state(tmp_path, monkeypatch):
    actions = ra.build_real_actions(backplane_root=tmp_path)

    # Nothing installed yet.
    assert actions.is_backplane_installed() is False
    assert actions.is_plugin_registered("dummy-plugin") is False

    monkeypatch.setattr(ra, "fetch_latest_release", lambda repo: _fake_release(repo))
    monkeypatch.setattr(ra, "fetch_manifest", lambda release: {"version": "1.0.0", "files": ["plugin.json"]})
    monkeypatch.setattr(
        ra,
        "fetch_release_files",
        lambda repo, tag, files: {"plugin.json": json.dumps({"name": "dummy-plugin"}).encode()},
    )

    actions.bootstrap_backplane()
    assert actions.is_backplane_installed() is True

    actions.install_plugin("dummy-plugin", "owner/dummy-plugin")
    assert actions.is_plugin_registered("dummy-plugin") is True

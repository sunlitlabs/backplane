"""Tests for the smart-launcher decision chain. Every side effect is
faked so these exercise exactly the branching logic itself -- which step
runs, in what order, and when the chain gives up -- not the real network/
filesystem operations those steps would perform in production (those are
already covered where they're actually implemented: updater.py, registry.py).
"""

from __future__ import annotations

import pytest

from backplane.installer.bootstrap import LaunchFailedError, LauncherActions, launch_plugin


def _actions(calls, **overrides):
    """``calls`` is created by the test itself so override lambdas defined
    in the test can log to the same list the defaults do."""
    defaults = dict(
        is_backplane_installed=lambda: calls.append("is_backplane_installed") or True,
        bootstrap_backplane=lambda: calls.append("bootstrap_backplane"),
        is_plugin_registered=lambda name: calls.append(f"is_plugin_registered:{name}") or True,
        install_plugin=lambda name, repo: calls.append(f"install_plugin:{name}"),
        launch_host=lambda: calls.append("launch_host"),
        ping_host=lambda: calls.append("ping_host") or True,
        request_show_plugin=lambda name: calls.append(f"request_show_plugin:{name}") or True,
        host_startup_timeout=1.0,
        host_poll_interval=0.05,
    )
    defaults.update(overrides)
    return LauncherActions(**defaults)


def test_host_already_running_and_plugin_known_just_shows_it():
    calls = []
    actions = _actions(calls)
    launch_plugin("dummy-plugin", "owner/dummy-plugin", actions)

    assert calls == ["ping_host", "request_show_plugin:dummy-plugin"]


def test_host_running_but_plugin_unknown_registers_then_shows():
    calls = []
    show_results = iter([False, True])
    actions = _actions(
        calls,
        request_show_plugin=lambda name: calls.append(f"request_show_plugin:{name}") or next(show_results),
    )
    launch_plugin("dummy-plugin", "owner/dummy-plugin", actions)

    assert calls == [
        "ping_host",
        "request_show_plugin:dummy-plugin",
        "install_plugin:dummy-plugin",
        "request_show_plugin:dummy-plugin",
    ]


def test_host_running_plugin_unknown_and_still_fails_after_install_raises():
    calls = []
    actions = _actions(calls, request_show_plugin=lambda name: calls.append(f"request_show_plugin:{name}") or False)
    with pytest.raises(LaunchFailedError):
        launch_plugin("dummy-plugin", "owner/dummy-plugin", actions)

    assert calls == [
        "ping_host",
        "request_show_plugin:dummy-plugin",
        "install_plugin:dummy-plugin",
        "request_show_plugin:dummy-plugin",
    ]


def test_fresh_machine_bootstraps_backplane_installs_plugin_and_launches_host():
    calls = []
    ping_results = iter([False, False, True])  # not running, then comes up after launch
    actions = _actions(
        calls,
        is_backplane_installed=lambda: calls.append("is_backplane_installed") or False,
        is_plugin_registered=lambda name: calls.append(f"is_plugin_registered:{name}") or False,
        ping_host=lambda: calls.append("ping_host") or next(ping_results),
    )
    launch_plugin("dummy-plugin", "owner/dummy-plugin", actions)

    assert calls == [
        "ping_host",
        "is_backplane_installed",
        "bootstrap_backplane",
        "is_plugin_registered:dummy-plugin",
        "install_plugin:dummy-plugin",
        "launch_host",
        "ping_host",
        "ping_host",
        "request_show_plugin:dummy-plugin",
    ]


def test_backplane_already_installed_and_plugin_registered_skips_both():
    calls = []
    ping_results = iter([False, True])  # not running yet, then comes up
    actions = _actions(calls, ping_host=lambda: calls.append("ping_host") or next(ping_results))
    launch_plugin("dummy-plugin", "owner/dummy-plugin", actions)

    # No bootstrap_backplane/install_plugin calls -- both already true.
    assert calls == [
        "ping_host",
        "is_backplane_installed",
        "is_plugin_registered:dummy-plugin",
        "launch_host",
        "ping_host",
        "request_show_plugin:dummy-plugin",
    ]


def test_host_never_becomes_reachable_after_launch_raises():
    calls = []
    actions = _actions(calls, ping_host=lambda: calls.append("ping_host") or False)
    with pytest.raises(LaunchFailedError):
        launch_plugin("dummy-plugin", "owner/dummy-plugin", actions)

    assert "launch_host" in calls
    assert not any(c.startswith("request_show_plugin") for c in calls)


def test_status_messages_are_reported_at_each_stage():
    calls = []
    ping_results = iter([False, False, True])
    actions = _actions(
        calls,
        is_backplane_installed=lambda: False,
        is_plugin_registered=lambda name: False,
        ping_host=lambda: next(ping_results),
    )
    statuses = []
    launch_plugin("dummy-plugin", "owner/dummy-plugin", actions, on_status=statuses.append)

    assert any("Setting up shared components" in s for s in statuses)
    assert any("Registering dummy-plugin" in s for s in statuses)
    assert any("Starting Backplane" in s for s in statuses)

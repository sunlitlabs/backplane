"""Integration test for the actual assembled HostProcess: a real
subprocess, with a real plugin pre-registered in a real registry.json,
confirming the host loads it, starts it, and is reachable over the real
control pipe -- the exact gap this hardening pass closed (previously,
every piece worked in isolation but nothing tied them into one running
host).
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path

from backplane.host.control_server import ping_host, request_show_plugin
from backplane.host.registry import PluginRegistry

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"


def _wait_for(predicate, timeout=10.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_real_host_process_loads_registered_plugin_and_answers_control_pipe(tmp_path):
    registry = PluginRegistry(tmp_path / "registry.json")
    registry.register("dummy-plugin", DUMMY_PLUGIN_DIR, {"name": "dummy-plugin"})

    control_address = rf"\\.\pipe\Backplane-Test-Host-{uuid.uuid4().hex[:12]}"

    # A short self-test window rather than terminate()-ing the process:
    # terminate() kills the host outright with no chance to run its own
    # shutdown(), which is what stops each plugin's subprocess -- an
    # orphaned plugin subprocess then holds its single-instance mutex
    # indefinitely and blocks every subsequent test run from starting a
    # fresh copy of the same plugin (caught by running this test
    # repeatedly back-to-back, not on a single run).
    proc = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "backplane.host.process",
            "--self-test",
            "6",
            "--data-dir",
            str(tmp_path),
            "--control-pipe-address",
            control_address,
        ],
    )
    try:
        assert _wait_for(lambda: ping_host(address=control_address, timeout=1.0), timeout=15)

        assert request_show_plugin("dummy-plugin", address=control_address, timeout=5) is True
        assert request_show_plugin("some-unregistered-plugin", address=control_address, timeout=5) is False
    finally:
        proc.wait(timeout=15)  # let the self-test's own shutdown() clean up its plugin subprocess

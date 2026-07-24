"""Smoke test for the Phase 0 skeleton: host process starts, shows a tray
icon, logs its lifecycle, and shuts down cleanly.

Runs the real process as a subprocess (not importing HostProcess directly)
since it owns a Tk mainloop and a real OS tray icon -- exercising it exactly
as it will actually run is more meaningful than mocking Tk/pystray out.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_host_process_starts_and_shuts_down_cleanly(tmp_path: Path) -> None:
    log_path = tmp_path / "backplane.log"

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "backplane.host.process",
            "--self-test",
            "1.5",
            "--log-path",
            str(log_path),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    log_text = log_path.read_text(encoding="utf-8")
    assert "Backplane host starting" in log_text
    assert "Backplane host shutting down" in log_text
    assert "Backplane host mainloop exited" in log_text
    assert "CRITICAL" not in log_text

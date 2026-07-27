"""Tests for Start Menu shortcut creation and startup registration --
against the real filesystem/registry, same testing philosophy as the rest
of this suite. Uses a uniquely-named Run key value so it can never collide
with (or accidentally remove) a real startup entry on this machine.
"""

from __future__ import annotations

import json
import subprocess
import uuid

from backplane.installer.shell_integration import (
    create_shortcut,
    is_registered_for_startup,
    remove_shortcut,
    set_run_on_startup,
)


_READ_SHORTCUT_SCRIPT = """
param([Parameter(Mandatory)][string]$Path)
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($Path)
ConvertTo-Json @{ TargetPath = $s.TargetPath; Arguments = $s.Arguments; IconLocation = $s.IconLocation }
"""


def _read_shortcut(path, tmp_path_factory):
    """Reads a .lnk's properties back via the same WScript.Shell COM
    object used to create it -- no pywin32, consistent with this project's
    no-pywin32-dependency rule. Written to a real script file and invoked
    via -File, matching this project's own rule against inline -Command
    strings for anything beyond a trivial one-liner."""
    script_path = tmp_path_factory.mktemp("read_shortcut") / "read_shortcut.ps1"
    script_path.write_text(_READ_SHORTCUT_SCRIPT, encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path), "-Path", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_create_shortcut_writes_a_real_lnk_with_correct_properties(tmp_path, tmp_path_factory):
    shortcut_path = tmp_path / "Test App.lnk"
    create_shortcut(
        shortcut_path,
        target_path=r"C:\Windows\System32\cmd.exe",
        arguments="/c echo hi",
        working_directory=str(tmp_path),
        icon_location=r"C:\Windows\System32\shell32.dll,4",
    )

    assert shortcut_path.exists()
    link = _read_shortcut(shortcut_path, tmp_path_factory)
    assert link["TargetPath"].lower() == r"C:\Windows\System32\cmd.exe".lower()
    assert link["Arguments"] == "/c echo hi"
    assert link["IconLocation"] == r"C:\Windows\System32\shell32.dll,4"


def test_remove_shortcut_deletes_the_file(tmp_path):
    shortcut_path = tmp_path / "Test App.lnk"
    create_shortcut(shortcut_path, target_path=r"C:\Windows\System32\cmd.exe")
    assert shortcut_path.exists()

    remove_shortcut(shortcut_path)
    assert not shortcut_path.exists()


def test_remove_shortcut_on_nonexistent_file_is_a_no_op(tmp_path):
    remove_shortcut(tmp_path / "does-not-exist.lnk")  # must not raise


def test_startup_registration_round_trips():
    name = f"BackplaneTest-{uuid.uuid4().hex[:8]}"
    try:
        assert not is_registered_for_startup(name)

        set_run_on_startup(name, command='"C:\\fake\\path.exe" --arg', enabled=True)
        assert is_registered_for_startup(name)

        set_run_on_startup(name, command="", enabled=False)
        assert not is_registered_for_startup(name)
    finally:
        set_run_on_startup(name, command="", enabled=False)  # cleanup, belt-and-suspenders


def test_disabling_a_never_registered_entry_is_a_no_op():
    name = f"BackplaneTest-{uuid.uuid4().hex[:8]}"
    set_run_on_startup(name, command="", enabled=False)  # must not raise
    assert not is_registered_for_startup(name)

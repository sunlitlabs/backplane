# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project

**Backplane** — a shared host-runtime library for small Windows tray
utilities. It owns the mechanical, repetitive parts (tray icon, global
hotkeys, settings, updates, install/uninstall) so individual tools only
implement their own domain logic against a small plugin contract.

Full design lives in [ARCHITECTURE.md](ARCHITECTURE.md) — read it before
making changes to the plugin contract, hosting model, update mechanism, or
registry behavior. This file is the quick-orientation summary; treat
ARCHITECTURE.md as the source of truth if the two ever disagree.

Environment-specific installation constraints (why the installer is built
the way it is) live in `private/cautions.md`, which is gitignored and never
published. Do not move that content into a tracked file, and do not restate
employer/environment specifics here or in any other tracked file — state
install/security behavior as neutral engineering requirements only.

## Status

**Backplane's core build (Part 1 of the approved plan) is complete, and a
follow-up hardening/integration pass has closed every gap a post-build
audit surfaced** — every mechanism built during the 10 phases is now
actually assembled into one running `HostProcess`, not just independently
tested. 130 tests, all real (real Win32 hotkeys/Credential Manager/
junctions/mutexes/registry, real subprocess IPC, real PowerShell verified
via the tool, not mocked).

What exists end-to-end, as one assembled host: `HostProcess` loads the
plugin registry at startup and spawns a `PluginSupervisor` per registered
plugin; runs the control server for real (a fixed pipe a smart-launcher
stub can reach); wires each plugin's tray presence, an auto-added
"Settings..." item for any plugin with a schema, and the host's own
About/Check-for-Updates items; runs periodic drift-checks (with a real
confirm-removal dialog) and a daily self-update check on Tk `after()`
scheduling; and renders toast notifications via a queued `ToastManager`.
The plugin contract now has both `register_hotkey`/`on_hotkey` and
`add_tray_item`/`on_tray_item` wired end-to-end over IPC, with a callback
pattern (`self.ipc.send(...)` looked up live at dispatch time, not frozen)
that keeps registrations working across a plugin crash/restart with no
re-registration step.

Two real bugs were caught specifically by testing the *assembled* system
rather than its pieces in isolation, and are worth knowing about if this
code is touched again: (1) `ControlServer` used to create a fresh
`Listener` per connection, which left a real gap where the pipe didn't
exist between closing the old one and binding the new one — fixed to bind
once and `accept()` repeatedly. (2) `HostProcess.__init__` used to start
the control server *before* loading registered plugins, so a caller could
see "host is alive" while `self._supervisors` was still empty — fixed by
loading plugins first. Testing this also required consolidating every
Tk-using test file onto one session-scoped root (see `tests/conftest.py`)
instead of each file's own — running the *whole* suite together crossed
the same Tcl multi-interpreter fragility that module-scoping had already
fixed at the single-file level.

Start Menu shortcuts and startup registration are now wired into install/
uninstall too: `install_plugin` creates a shortcut (pointing at the same
`launch_cli` smart-launcher entrypoint) when a plugin's manifest asks for
one; `uninstall_plugin` removes it via the same path-computing function,
so the two can't drift apart; `bootstrap_backplane` registers the host's
own one-time HKCU Run key entry. Per-plugin "run on startup" is a
different question from a Windows Run key now that there's one always-on
host -- it just controls whether `HostProcess` auto-starts that plugin's
supervisor when the host comes up (already wired in the integration pass
above), not a separate per-plugin registry key.

**A real release now exists.** `sunlitlabs/backplane` v1.2.0 is tagged and
published on GitHub, with `manifest.json` uploaded as a release asset (via
`installer/generate_manifest.py`, then never committed -- it's gitignored,
regenerate it fresh before cutting each release). Verified against the
*live* repo, unauthenticated, exactly as a fresh machine would: `fetch_
latest_release`/`fetch_manifest`/`fetch_release_files` all resolve
correctly and the downloaded file content matches the working tree.

That verification surfaced one real gap: the repo was private, which
silently breaks the credential-free bootstrap path (`releases/latest`
404s with no credentials). The repo is now public -- this is required for
the smart-launcher's zero-touch install to work at all, since a
fresh machine has nothing to authenticate with. `private/cautions.md`
stays gitignored regardless; publicness is about the code, not about
exposing anything environment- or employer-specific.

**Next**: Part 2 of the plan — migrate py-sensor, then CrierTTS, then
L10 Manager onto this, in that order (see the plan file referenced in
memory, or ARCHITECTURE.md's migration notes).

## Commands

Run from this repo's root, using the local dev venv:

```bash
# One-time setup
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"

# Run the host process (shows a tray icon)
.venv/Scripts/python -B -m backplane.host.process

# Smart-launcher chain for a plugin (bootstraps Backplane/registers the
# plugin/launches the host as needed, then asks it to show the plugin)
.venv/Scripts/python -B -m backplane.installer.launch_cli <plugin-name> <owner/repo>

# Regenerate the release manifest (before cutting a release)
.venv/Scripts/python -B -m backplane.installer.generate_manifest

# Run the test suite
.venv/Scripts/python -B -m pytest tests/ -v
```

## Architecture (summary — see ARCHITECTURE.md for detail)

- **One host process** per machine, launched at login, manages every
  registered plugin as its own subprocess.
- **Plugins** are isolated subprocesses, each free to use its own UI toolkit
  for domain-specific windows. They talk to the host only through an
  abstract `host` API (hotkeys, tray items, settings, secrets, notify) —
  never touching OS/tray/hotkey libraries directly.
- **Single shared install** under one publisher namespace (`Sunlit Labs`),
  not vendored per plugin. Plugins register with Backplane at install time
  and deregister at uninstall time; Backplane's registry (not a folder scan)
  is the source of truth for what's installed.
- **Settings** are centralized in Backplane's own store, namespaced per
  plugin, with schema versioning/migration on load.
- **Updates** trigger off GitHub Releases (SemVer, `vX.Y.Z` tags) on a
  schedule (on launch + daily), apply via versioned folders + a `current`
  pointer (never overwrite in place), and prune old versions once a new one
  is confirmed stable.
- **"Solo" vs. "combined" tray icon** is a hosting-mode setting on the one
  host process, not a separate install or product.
- **Crash/restart**: a dying plugin subprocess gets restarted (capped
  attempts within a rolling window; past the cap, the host gives up rather
  than respawning forever). Its hotkey/tray registrations are never
  unregistered and re-registered — the registered callback looks up the
  live IPC connection at dispatch time, so it just starts reaching the new
  subprocess the moment it reconnects.

## Key Design Rules

- **No compiled executables.** Installs are plain Python scripts/venvs.
- **Never `iex`/`Invoke-Expression`/`ScriptBlock::Create` on downloaded
  content.** PowerShell scripts are always invoked via `-File` with
  `-ExecutionPolicy Bypass` scoped to that single process — never a
  persistent policy change.
- **Never require administrator rights.** Everything installs per-user.
- **Uninstall is always complete.** One canonical teardown routine (files,
  Start Menu entry, startup registration, hotkeys, tray presence, settings)
  — used both for explicit uninstall and for a plugin Backplane concludes
  was removed out-of-band. No partial cleanup paths.
- **Don't purge on a single miss.** A registered plugin whose files can't be
  found gets a retry window (handles slow cloud-sync folders) before
  Backplane treats it as uninstalled, and confirms with the user before
  purging settings.
- **All Backplane-based repos share one versioning scheme** (SemVer) so the
  update mechanism is uniform across all of them.

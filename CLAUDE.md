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

Implementation in progress. Building Backplane itself first (10 phases,
tracked in the approved build plan); the three existing tools
(py-sensor, CrierTTS, L10 Manager) get migrated onto it afterward, in that
order. Done so far: Phase 0 (host process skeleton), Phase 1 (raw
RegisterHotKey-based hotkey manager with conflict detection), Phase 2
(host/plugin subprocess split with named-pipe IPC), Phase 3 (centralized
settings store with schema-defaults migration, generic schema-driven
settings UI with conditional sections, and secrets via Credential Manager),
Phase 4 (toolkit-agnostic single-instance guard via a named mutex,
consistent taskbar identity across however many windows a plugin opens, and
a close-behavior setting a plugin's own window-close code can consult), and
Phase 5 (TrayModel: one icon per plugin or one combined icon from the same
registered plugin data, proving solo-vs-combined is genuinely just a
display-mode setting), Phase 6 (plugin registry: install/uninstall as
the registration trigger, bounded-retry drift detection for a plugin whose
files went missing, and the one canonical uninstall routine tearing down
tray presence, hotkeys, settings, and secrets), and Phase 7 (the updater:
GitHub Releases + SemVer as the trigger, versioned-folder + directory-
junction installs so updates never overwrite in place, rollback as just
re-pointing the junction back, pruning old versions only once the current
one has proven it starts, and the update-now/wait/skip + progress +
restart-now/later dialog flow), and Phase 8 (the smart-launcher: a fixed
control pipe so a separate process can find an already-running host, the
idempotent launch decision chain -- ping host, bootstrap Backplane if
missing, register the plugin if missing, launch and wait for the host --
Start Menu shortcut + startup-registration helpers, and the PowerShell
layer: ported PythonCheck.ps1/CreateShortcut.ps1/StopRunningInstance.ps1,
a stdlib-only bootstrap_standalone.py for the truly-fresh-machine case,
and the one-file plugin launcher stub template) -- all proven end-to-end
with dummy test plugins over real IPC, the junction/pruning mechanism and
shell integration against the real filesystem/registry, and the PowerShell
helpers verified for real (not just written).

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

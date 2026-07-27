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

**Backplane's core build (Part 1 of the approved plan) is complete** —
all 10 phases (0 through 9), 118 tests, all real (real Win32 hotkeys/
Credential Manager/junctions/mutexes/registry, real subprocess IPC, real
PowerShell verified via the tool, not mocked). Phase-by-phase detail is in
git history (`git log --oneline`, tags `v0.1.0`..`v1.0.0`) rather than
duplicated here.

What exists end-to-end: a host process that manages plugin subprocesses
over named-pipe IPC; hotkeys (raw `RegisterHotKey`, in-process + OS-level
conflict detection, a live-capture Tk widget); centralized settings
(schema-driven UI, conditional sections) and secrets (Credential Manager);
a tray model where solo-vs-combined is just a display setting; a plugin
registry with bounded-retry drift detection and one canonical uninstall
routine; an updater (GitHub Releases + SemVer, versioned-folder +
junction installs, rollback, pruning); a smart-launcher chain (fixed
control pipe, idempotent bootstrap-or-launch, PowerShell prerequisite
bootstrap) that's simultaneously a plugin's installer and its permanent
run icon; and a crash/restart supervisor that preserves a plugin's
hotkey/tray registrations across a crash without ever re-registering them
from scratch (verified by test, including the case that would silently
break: the callback closing over a live attribute, not a frozen
connection).

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

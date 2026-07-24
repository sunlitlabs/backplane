# Backplane — Architecture

## Goal

Backplane is middleware: it owns the mechanical, repetitive parts of building a
small Windows tray utility (tray icon, hotkeys, settings, updates, install)
so that each individual tool only has to implement its own domain logic and
declare what it needs through a contract.

Plugins never talk to the OS or to UI toolkits directly for these concerns —
they call an abstract `host` API, and Backplane does the actual work. This
keeps behavior consistent across tools and means solo-hosted and
managed-hosted plugins are running identical code paths.

## Hosting model: one host process, subprocess-isolated plugins

Backplane runs as a single, always-running host process per machine
(launched at login) — not as N independent processes each embedding their
own copy of the library. That process owns:

- The tray icon(s) and menu(s)
- Centralized global hotkey registration and dispatch — in-process, since
  there's only one process registering hotkeys. This also means a hotkey
  conflict between two Backplane-hosted plugins can't happen; only a
  conflict with some other, non-Backplane application remains possible, and
  that's caught via the OS-level registration failure.
- The plugin registry and centralized settings store (see below)
- Shared "chrome" windows: settings shell, update-progress dialog, toast
  notifications, about page

Each registered plugin still runs as its own **subprocess**, managed by the
host process — this preserves UI-toolkit independence (a plugin keeps
whatever toolkit it's already built with for its own domain-specific
windows), crash isolation, and clean single-instance semantics.

A plugin may need more than one simultaneous running copy of itself — e.g.
a tool whose data lives in a user-chosen folder, where the user wants two
different folders open side by side. This is supported as multiple
subprocesses of the *same* plugin, each identified by a launch parameter
the host passes through, not as separate registry entries. Code
registration and the plugin's settings/secret store stay singular per
plugin per machine; if a plugin needs finer-grained scoping (a secret that
should differ per running copy), it sub-keys its own
`get_secret()`/`set_secret()` calls using a key it derives itself — the
host's stores stay plain per-plugin key/value stores and don't need any
built-in notion of "instances."

**"Solo" vs. "combined" is a tray-icon display setting on the one host
process, not a separate install or process model.** Whether each plugin gets
its own tray icon or every registered plugin shares one combined icon is
just a hosting-mode setting. This is also why a separate "Plugboard" product
isn't currently needed — see Open questions.

### UI toolkit decision

Because plugins run as isolated subprocesses, there is no technical
requirement for every plugin to share one UI toolkit for their own
domain-specific windows — a plugin already built in one toolkit does not need
to be migrated to another just to participate.

Backplane's own shared chrome (settings shell, progress dialog, toast
notifications, about page) is implemented once, in **Tkinter**:

- It's stdlib — no extra dependency has to be bundled/installed for every
  single install, which matters when installs need to be lightweight and
  reliable.
- It renders generically from each plugin's settings schema (see below)
  rather than from the plugin's own widget code, so the plugin's UI toolkit
  choice doesn't matter for this shared surface at all.

Net effect: no forced migration of any existing tool's own UI. Only
Backplane's new shared chrome needs a toolkit decision, and that's Tkinter.

## Plugin contract

Each plugin ships a manifest and an entry point implementing a small
interface. Sketch:

```json
// plugin.json
{
  "name": "example-tool",
  "display_name": "Example Tool",
  "version": "1.4.2",
  "icon": "icon.ico",
  "entrypoint": "example_tool.plugin:Plugin",
  "hotkeys": [{"id": "do_thing", "default": "ctrl+alt+e"}],
  "settings_schema": "settings_schema.json",
  "show_tray_icon_default": true,
  "create_start_menu_entry_default": true,
  "run_on_startup_default": false,
  "close_behavior_default": "minimize_to_tray",
  "update": {"repo": "owner/example-tool"}
}
```

```python
class PluginBase:
    def on_load(self, host): ...       # host = abstraction over tray/hotkeys/settings/notify
    def on_hotkey(self, hotkey_id): ...
    def get_menu_items(self): ...
    def start(self): ...
    def stop(self): ...
```

Plugins never touch `pystray`/hotkey libraries/registry APIs directly — only
`host.register_hotkey(...)`, `host.add_tray_item(...)`, `host.get_settings()`,
`host.notify(...)`, etc.

### Per-app-defaulted settings

Several behaviors are host-managed settings that each plugin declares a
*default* for, but the user can override per install:

- Show tray icon (yes/no)
- Create Start Menu entry (yes/no)
- Run on startup (yes/no)
- Close-button behavior (quit vs. minimize-to-tray)

## Plugin registry

Plugins register with Backplane at install time and deregister at uninstall
time — Backplane's registry, not a folder scan, is the source of truth for
what's installed.

- **Drift detection**: if Backplane can't find a registered plugin's files
  (missing entrypoint, deleted folder), it doesn't treat that as an
  immediate uninstall. It retries over a several-minute window (short
  interval, bounded total wait) to absorb something like a slow cloud-sync
  folder — a single momentary miss must never trigger a silent purge. Only
  once that window is exhausted does Backplane treat the plugin as removed,
  and it confirms with the user before purging settings rather than
  assuming.
- **Uninstall must be complete.** There is exactly one canonical uninstall
  routine, used both when the user explicitly uninstalls a plugin and when
  Backplane concludes a plugin was removed out-of-band. It always tears down
  everything the install touched — installed files, Start Menu entry,
  startup registration, registered hotkeys, tray presence, and (with
  confirmation) settings/data in the central store — never a partial subset.

## Settings

- Held centrally in Backplane's own settings store (namespaced per plugin),
  not inside each plugin's own install folder — consistent with Backplane
  being a single shared install rather than something each plugin vendors.
- **Schema versioning**: each settings file records the schema version it was
  written with. On load, Backplane runs any needed migration steps (fill new
  keys with defaults, transform renamed/restructured keys, warn on unknown
  deprecated keys) rather than either crashing or silently discarding user
  settings on an update.
- Nested/conditional sections are supported in the schema (a plugin can
  declare a sub-panel that only appears depending on another setting's value)
  so plugin-specific sub-configuration renders through the same generic
  mechanism as top-level settings.
- Secrets (API tokens, keys) are **not** stored in the plain settings JSON —
  Backplane exposes a separate `host.get_secret()`/`host.set_secret()` backed
  by Windows Credential Manager.

## Updates

- **Trigger**: GitHub Releases. Every Backplane-based repo uses the same
  versioning scheme (Semantic Versioning — `MAJOR.MINOR.PATCH`, tagged as
  `vX.Y.Z`) so the update check is uniform: compare the latest published
  release tag against a local version file.
- **Check cadence**: on launch, and if not already checked today, once every
  24 hours thereafter (for tools that run continuously). A manual "Check for
  Updates" is also always available from the tray menu.
- **Application mechanic**: a manifest listing exactly which files changed in
  the new release, applied as direct per-file downloads — not a full
  reinstall/re-run of the installer for every update, and not a `git pull`
  (updates must not assume git or a working-tree checkout are present).
  Dependencies are only (re)installed via pip when the plugin's own
  requirements actually changed, not on every update.
- **UI flow**: on finding an update, ask the user to update now, wait, or
  skip this version. Applying shows a progress window. On completion, ask
  whether to restart now or later.
- **Versioning & rollback**: each update writes into a fresh
  `versions/<version>/` folder and flips a `current` pointer, rather than
  overwriting files in place. A process already running keeps using
  whatever version it loaded at its own startup; rollback is just
  re-pointing `current` back, not restoring a backup. Applies to both
  Backplane's own updates and each plugin's updates.
- **Version retention**: old version folders don't accumulate indefinitely.
  Once a new version has been confirmed to start successfully at least once,
  everything older than the current + immediately-previous version is
  pruned automatically — the previous version is kept only long enough to
  serve as the one-step rollback target.
- **First-run large asset downloads** (e.g. a bundled ML model) are handled
  as a distinct flow from a code update — same progress-window UI, different
  trigger (first run / missing asset, not a version bump).

## Notifications

A shared toast/notification system (`host.notify(title, message, ...)`) is
available to any plugin, not just the updater — e.g. a monitoring tool
alerting on a threshold. Built once in Backplane so all tools look and behave
consistently.

## Hotkeys

- Registration goes through `host.register_hotkey(id, combo, callback)`.
- A shared "press keys to record a hotkey" capture control: a read-only field
  that records a live key combination (requiring at least one modifier) and
  formats it for display, rather than requiring the user to type a combo as
  text.
- **Conflict detection**: when registering a hotkey (default or user-set),
  Backplane checks it against every other hotkey it knows about and surfaces
  a clear message rather than silently failing. Because plugins can also run
  standalone in separate processes (not just as plugins under one host),
  OS-level registration failure (another process already owns that combo) is
  also caught and surfaced, not just in-process conflicts.

## Single-instance guarding

Every plugin gets a toolkit-agnostic single-instance guard (not tied to any
particular GUI library) so the same plugin can't end up running twice at once
— e.g. launched solo while already running under a managed host, or launched
twice by accident — which would otherwise double-register hotkeys or corrupt
shared state.

## Install / uninstall

- **Publisher namespace**: every install lives under one publisher folder —
  `Sunlit Labs` (github.com/sunlitlabs) — e.g.
  `%LOCALAPPDATA%\Sunlit Labs\Backplane\...`, with matching Start Menu folder
  grouping and registry key namespace.
- **Single shared install**: Backplane itself installs once per machine
  under that namespace; plugins register with it rather than each vendoring
  a private copy (see Plugin registry).
- **The smart-launcher stub**: each plugin distributes exactly one
  artifact — a small, rarely-changing script that is simultaneously its
  installer and its permanent "run" icon. Every time it runs, it performs
  the same idempotent chain: if Backplane's host is already running, ask it
  to show/focus this plugin; if Backplane is installed but not running,
  launch it first; if Backplane isn't installed at all, bootstrap it
  (including Python/pip if missing) with a brief progress notice; if this
  plugin isn't registered yet, register it — then continue. There is no
  separate one-time installer distinct from the everyday run shortcut, so a
  fresh machine and the thousandth launch go through identical code.
- No compiled executables — installs are plain Python scripts/venvs, matching
  the approach already used across this tool ecosystem. See `private/` for
  the specific environment constraints this satisfies (not published here).
- Installer bootstraps its own prerequisites: checks for a real Python
  install and pip, and installs them if missing, rather than only detecting
  and telling the user to do it manually.
- Uninstall is symmetric with install and follows the same canonical,
  complete teardown routine described under Plugin registry: Start Menu
  entry, startup registration, hotkeys, tray presence, and (with
  confirmation) settings/data — not just the installed files.

## Open questions / next steps

- Concrete `host` API surface (final function signatures/behavior) —
  ownership assigned, to be finalized during implementation planning.
- Whether the "combined tray icon" experience ever needs to be a distinctly
  branded/separate product rather than just a Backplane hosting-mode
  setting — deferred; revisit only if a real architectural need forces it.
- Naming for that combined-icon experience, if it ever does become its own
  thing (parked, not decided).

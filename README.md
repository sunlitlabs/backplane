# Backplane

A shared host runtime for small Windows tray utilities. One library provides:

- Tray icon + menu management
- Global hotkey registration, conflict detection, and a press-to-record capture UI
- Settings persistence with schema versioning/migration
- Update checking against versioned releases, with rollback
- Toast notifications and other shared UI chrome (progress dialogs, about page)
- Install / uninstall scaffolding, start-menu shortcuts, run-on-startup toggle

Tools built on Backplane can run two ways:

- **Solo** — a tool's own launcher hosts just itself: one tray icon, its own
  hotkeys, its own settings. Looks and behaves like an ordinary standalone app.
- **Managed** — a separate host process discovers every Backplane-based tool
  installed on the machine and hosts them all under a single tray icon.

Both paths run through the exact same library code — there's no separate
"solo mode" implementation to drift out of sync with the managed one; the only
difference is how many plugins a given host process is told to load.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

Environment-specific installation notes live in `private/` (gitignored, not
published).

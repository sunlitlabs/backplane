"""Generic, schema-driven settings window.

Renders a form from a plugin's settings_schema.json rather than each
plugin building its own dialog -- this is what lets Backplane centralize
settings UI across every plugin regardless of that plugin's own UI
toolkit, and lets a plugin declare a conditionally-visible sub-panel
(nested settings, e.g. per-provider options) through the schema alone,
with no plugin-specific widget code needed for the settings surface.

Secret fields never appear in ``values`` -- their current value (if any)
is fetched via ``get_secret`` when the field is added, and changes are
reported separately from ordinary field values on save, since secrets are
never meant to round-trip through the plain settings JSON.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, Optional, Tuple


class SettingsWindow:
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        schema: Dict[str, Any],
        values: Dict[str, Any],
        on_save: Callable[[Dict[str, Any], Dict[str, str]], None],
        get_secret: Optional[Callable[[str], Optional[str]]] = None,
    ):
        self._schema = schema
        self._on_save = on_save
        self._get_secret = get_secret or (lambda key: None)

        self._vars: Dict[str, tk.Variable] = {}
        self._rows: Dict[str, Tuple[tk.Widget, tk.Widget]] = {}
        self._secret_keys: set = set()

        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.resizable(False, False)

        form = ttk.Frame(self.window, padding=12)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        for i, field in enumerate(schema.get("fields", [])):
            self._add_field(form, i, field, values)

        button_row = ttk.Frame(self.window, padding=(12, 0, 12, 12))
        button_row.grid(row=1, column=0, sticky="e")
        ttk.Button(button_row, text="Cancel", command=self.window.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(button_row, text="Save", command=self._save).grid(row=0, column=1, padx=4)

        self._apply_visibility()

    def _add_field(self, form: ttk.Frame, row: int, field: Dict[str, Any], values: Dict[str, Any]) -> None:
        key = field["key"]
        label_text = field.get("label", key)
        field_type = field.get("type", "string")

        label = ttk.Label(form, text=label_text)
        label.grid(row=row, column=0, sticky="w", pady=2, padx=(0, 8))

        if field_type == "boolean":
            var: tk.Variable = tk.BooleanVar(value=bool(values.get(key, field.get("default", False))))
            widget: tk.Widget = ttk.Checkbutton(form, variable=var)
        elif field_type == "secret":
            var = tk.StringVar(value=self._get_secret(key) or "")
            widget = ttk.Entry(form, textvariable=var, show="*")
            self._secret_keys.add(key)
        elif field_type == "integer":
            default_val = values.get(key, field.get("default", 0))
            var = tk.IntVar(value=int(default_val or 0))
            widget = ttk.Entry(form, textvariable=var)
        else:
            var = tk.StringVar(value=str(values.get(key, field.get("default", ""))))
            widget = ttk.Entry(form, textvariable=var)

        widget.grid(row=row, column=1, sticky="ew", pady=2)
        self._vars[key] = var
        self._rows[key] = (label, widget)

        show_if = field.get("show_if")
        if show_if:
            controlling_var = self._vars.get(show_if["key"])
            if controlling_var is not None:
                controlling_var.trace_add("write", lambda *_args: self._apply_visibility())

    def _apply_visibility(self) -> None:
        for field in self._schema.get("fields", []):
            key = field["key"]
            show_if = field.get("show_if")
            row = self._rows.get(key)
            if row is None:
                continue
            label, widget = row

            visible = True
            if show_if:
                controlling_var = self._vars.get(show_if["key"])
                if controlling_var is not None:
                    visible = controlling_var.get() == show_if.get("equals")

            if visible:
                label.grid()
                widget.grid()
            else:
                label.grid_remove()
                widget.grid_remove()

    def _save(self) -> None:
        values: Dict[str, Any] = {}
        secrets: Dict[str, str] = {}
        for field in self._schema.get("fields", []):
            key = field["key"]
            var = self._vars.get(key)
            if var is None:
                continue
            if key in self._secret_keys:
                secrets[key] = var.get()
            else:
                values[key] = var.get()
        self._on_save(values, secrets)
        self.window.destroy()

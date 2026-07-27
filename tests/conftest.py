"""Shared pytest fixtures.

``tk_root``: ONE Tk() for the entire test session, shared across every
Tk-dependent test file. Repeatedly creating and destroying Tcl
interpreters within a single process is a well-known Tkinter fragility --
each individual test file's own module-scoped root worked in isolation,
but running the full suite together (many files, each creating their own)
crossed the same threshold at a coarser granularity and produced the exact
same "can't find a usable tk.tcl" errors. A single session-scoped root
sidesteps it entirely: every chrome window in these tests is a Toplevel
child of this one root, never a fresh Tk() of its own.
"""

from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()

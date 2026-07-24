"""Subprocess entrypoint for a plugin:

    python -m backplane.plugin_runtime.main <plugin_dir> <ipc_address>

This is what the host process (subprocess_manager.py) spawns for every
registered plugin.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from backplane.plugin_runtime.loader import run_plugin


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print(
            "usage: python -m backplane.plugin_runtime.main <plugin_dir> <ipc_address>",
            file=sys.stderr,
        )
        return 2
    plugin_dir = Path(argv[0])
    ipc_address = argv[1]
    run_plugin(plugin_dir, ipc_address)
    return 0


if __name__ == "__main__":
    sys.exit(main())

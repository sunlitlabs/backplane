"""CLI entrypoint the plugin smart-launcher stub calls once Backplane's
own code is on disk (see bootstrap_standalone.py for the truly-first-run
case):

    python -m backplane.installer.launch_cli <plugin-name> <plugin-repo>

Wires the real install machinery (real_actions.py) into the decision
chain (bootstrap.py) and runs it.
"""

from __future__ import annotations

import sys
from typing import List, Optional

from backplane.installer.bootstrap import LaunchFailedError, launch_plugin
from backplane.installer.real_actions import build_real_actions


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print("usage: python -m backplane.installer.launch_cli <plugin-name> <plugin-repo>", file=sys.stderr)
        return 2

    plugin_name, plugin_repo = argv[0], argv[1]
    actions = build_real_actions()

    try:
        launch_plugin(plugin_name, plugin_repo, actions, on_status=print)
    except LaunchFailedError as exc:
        print(f"Failed to launch {plugin_name}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""A plugin that crashes immediately on start() -- used only to exercise
PluginSupervisor's crash-loop cap. Not a real product plugin.
"""

from __future__ import annotations

import sys

from backplane.contracts import PluginBase


class CrashyPlugin(PluginBase):
    def on_load(self, host) -> None:
        pass

    def start(self) -> None:
        sys.exit(1)

"""Tests for TrayModel: proving solo-vs-combined is genuinely just a
display-mode setting -- same registered plugin data, only the number of
underlying Tray/pystray.Icon instances and how their menus are shaped
changes when the mode flips.
"""

from __future__ import annotations

from backplane.host.tray import TrayItem
from backplane.host.tray_model import PluginTrayInfo, TrayModel


def _menu_labels(menu):
    return [item.text for item in menu]


def test_separate_mode_gives_one_tray_per_plugin():
    model = TrayModel(mode="separate")
    try:
        model.register_plugin(PluginTrayInfo("plugin-a", "Plugin A"))
        model.register_plugin(PluginTrayInfo("plugin-b", "Plugin B"))
        assert model.tray_count() == 2
    finally:
        model.stop()


def test_combined_mode_gives_exactly_one_tray_regardless_of_plugin_count():
    model = TrayModel(mode="combined")
    try:
        model.register_plugin(PluginTrayInfo("plugin-a", "Plugin A"))
        model.register_plugin(PluginTrayInfo("plugin-b", "Plugin B"))
        model.register_plugin(PluginTrayInfo("plugin-c", "Plugin C"))
        assert model.tray_count() == 1
    finally:
        model.stop()


def test_flipping_mode_changes_only_tray_count_not_registered_plugins():
    model = TrayModel(mode="separate")
    try:
        model.register_plugin(PluginTrayInfo("plugin-a", "Plugin A"))
        model.register_plugin(PluginTrayInfo("plugin-b", "Plugin B"))
        assert model.tray_count() == 2

        model.set_mode("combined")
        assert model.tray_count() == 1
        assert set(model._plugins.keys()) == {"plugin-a", "plugin-b"}  # unchanged

        model.set_mode("separate")
        assert model.tray_count() == 2
        assert set(model._plugins.keys()) == {"plugin-a", "plugin-b"}  # still unchanged
    finally:
        model.stop()


def test_unregistering_a_plugin_removes_its_tray_in_separate_mode():
    model = TrayModel(mode="separate")
    try:
        model.register_plugin(PluginTrayInfo("plugin-a", "Plugin A"))
        model.register_plugin(PluginTrayInfo("plugin-b", "Plugin B"))
        assert model.tray_count() == 2

        model.unregister_plugin("plugin-a")
        assert model.tray_count() == 1
        assert model.get_tray("plugin-a") is None
        assert model.get_tray("plugin-b") is not None
    finally:
        model.stop()


def test_combined_menu_contains_a_submenu_per_plugin_and_one_exit_item():
    model = TrayModel(mode="combined")
    try:
        model.register_plugin(
            PluginTrayInfo("plugin-a", "Plugin A", menu_items=[TrayItem("Settings...", lambda: None)])
        )
        model.register_plugin(
            PluginTrayInfo("plugin-b", "Plugin B", menu_items=[TrayItem("Open", lambda: None)])
        )

        combined_tray = model.get_tray("__combined__")
        labels = _menu_labels(combined_tray._icon.menu)

        assert "Plugin A" in labels
        assert "Plugin B" in labels
        assert "Exit Backplane" in labels
    finally:
        model.stop()


def test_separate_mode_menu_has_plugin_items_plus_exit():
    model = TrayModel(mode="separate")
    try:
        model.register_plugin(
            PluginTrayInfo("plugin-a", "Plugin A", menu_items=[TrayItem("Settings...", lambda: None)])
        )
        tray_a = model.get_tray("plugin-a")
        labels = _menu_labels(tray_a._icon.menu)
        assert labels == ["Settings...", "Exit"]
    finally:
        model.stop()


def test_updating_a_plugins_menu_reflects_without_changing_tray_count():
    model = TrayModel(mode="separate")
    try:
        model.register_plugin(PluginTrayInfo("plugin-a", "Plugin A"))
        assert model.tray_count() == 1

        model.update_plugin_menu("plugin-a", [TrayItem("New Item", lambda: None)])
        assert model.tray_count() == 1  # same tray instance, just a new menu

        tray_a = model.get_tray("plugin-a")
        labels = _menu_labels(tray_a._icon.menu)
        assert "New Item" in labels
    finally:
        model.stop()

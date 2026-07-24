"""Unit tests for the centralized, schema-driven settings store."""

from __future__ import annotations

from pathlib import Path

from backplane.host.settings_store import SCHEMA_VERSION_KEY, SettingsStore

SCHEMA = {
    "version": 2,
    "fields": [
        {"key": "port", "type": "integer", "default": 8765},
        {"key": "enabled", "type": "boolean", "default": True},
        {"key": "api_key", "type": "secret"},
    ],
}


def test_load_fills_defaults_for_missing_keys(tmp_path: Path):
    store = SettingsStore(tmp_path)
    values = store.load("some-plugin", SCHEMA)
    assert values["port"] == 8765
    assert values["enabled"] is True
    assert "api_key" not in values  # secrets never live in the plain file
    assert values[SCHEMA_VERSION_KEY] == 2


def test_save_and_reload_round_trips(tmp_path: Path):
    store = SettingsStore(tmp_path)
    store.load("some-plugin", SCHEMA)
    store.save("some-plugin", {"port": 9999, "enabled": False, SCHEMA_VERSION_KEY: 2})

    reloaded = store.load("some-plugin", SCHEMA)
    assert reloaded["port"] == 9999
    assert reloaded["enabled"] is False


def test_existing_settings_survive_a_schema_gaining_a_field(tmp_path: Path):
    """Simulates an update where the plugin's schema grows a new field --
    an existing settings file (as if written by an older version) must get
    the new field's default filled in, not be discarded or crash."""
    store = SettingsStore(tmp_path)
    old_schema = {"version": 1, "fields": [{"key": "port", "type": "integer", "default": 8765}]}
    store.load("some-plugin", old_schema)
    store.save("some-plugin", {"port": 1234, SCHEMA_VERSION_KEY: 1})

    new_schema = {
        "version": 2,
        "fields": [
            {"key": "port", "type": "integer", "default": 8765},
            {"key": "new_field", "type": "boolean", "default": True},
        ],
    }
    migrated = store.load("some-plugin", new_schema)
    assert migrated["port"] == 1234  # existing value preserved
    assert migrated["new_field"] is True  # new field filled with its default


def test_merge_and_save_only_touches_given_keys(tmp_path: Path):
    store = SettingsStore(tmp_path)
    store.load("some-plugin", SCHEMA)
    store.save("some-plugin", {"port": 1111, "enabled": True, SCHEMA_VERSION_KEY: 2})

    result = store.merge_and_save("some-plugin", SCHEMA, {"enabled": False})
    assert result["port"] == 1111  # untouched
    assert result["enabled"] is False  # updated

    reloaded = store.load("some-plugin", SCHEMA)
    assert reloaded["port"] == 1111
    assert reloaded["enabled"] is False


def test_settings_for_different_plugins_are_isolated(tmp_path: Path):
    store = SettingsStore(tmp_path)
    store.load("plugin-a", SCHEMA)
    store.save("plugin-a", {"port": 1, SCHEMA_VERSION_KEY: 2})
    store.load("plugin-b", SCHEMA)
    store.save("plugin-b", {"port": 2, SCHEMA_VERSION_KEY: 2})

    assert store.load("plugin-a", SCHEMA)["port"] == 1
    assert store.load("plugin-b", SCHEMA)["port"] == 2

"""Real Windows Credential Manager round-trip tests -- direct ctypes
against CredWriteW/CredReadW/CredDeleteW, not a mock, since the whole
point of this module is that the real Win32 API behaves correctly.
"""

from __future__ import annotations

import uuid

import pytest

from backplane.host.secrets import delete_all_secrets, delete_secret, get_secret, set_secret


@pytest.fixture
def namespace():
    # Unique per test run so parallel/repeated runs never collide with a
    # leftover credential from a previous run.
    ns = f"backplane-test-{uuid.uuid4().hex[:8]}"
    yield ns
    # Best-effort cleanup of anything this test might have written.
    for key in ("api_key", "token", "missing"):
        try:
            delete_secret(ns, key)
        except Exception:
            pass


def test_get_secret_returns_none_when_unset(namespace):
    assert get_secret(namespace, "missing") is None


def test_set_then_get_round_trips(namespace):
    set_secret(namespace, "api_key", "sk-test-12345")
    assert get_secret(namespace, "api_key") == "sk-test-12345"


def test_set_overwrites_existing_value(namespace):
    set_secret(namespace, "token", "first-value")
    set_secret(namespace, "token", "second-value")
    assert get_secret(namespace, "token") == "second-value"


def test_delete_removes_the_secret(namespace):
    set_secret(namespace, "api_key", "sk-test-12345")
    delete_secret(namespace, "api_key")
    assert get_secret(namespace, "api_key") is None


def test_delete_of_nonexistent_secret_is_a_no_op(namespace):
    delete_secret(namespace, "missing")  # must not raise


def test_delete_all_secrets_removes_every_key_in_the_namespace(namespace):
    set_secret(namespace, "api_key", "value-1")
    set_secret(namespace, "token", "value-2")

    deleted_count = delete_all_secrets(namespace)

    assert deleted_count == 2
    assert get_secret(namespace, "api_key") is None
    assert get_secret(namespace, "token") is None


def test_delete_all_secrets_does_not_touch_other_namespaces():
    ns_a = f"backplane-test-a-{uuid.uuid4().hex[:8]}"
    ns_b = f"backplane-test-b-{uuid.uuid4().hex[:8]}"
    try:
        set_secret(ns_a, "api_key", "value-a")
        set_secret(ns_b, "api_key", "value-b")

        delete_all_secrets(ns_a)

        assert get_secret(ns_a, "api_key") is None
        assert get_secret(ns_b, "api_key") == "value-b"
    finally:
        delete_secret(ns_a, "api_key")
        delete_secret(ns_b, "api_key")


def test_delete_all_secrets_on_empty_namespace_is_a_no_op():
    ns = f"backplane-test-empty-{uuid.uuid4().hex[:8]}"
    assert delete_all_secrets(ns) == 0


def test_different_namespaces_are_isolated():
    ns_a = f"backplane-test-a-{uuid.uuid4().hex[:8]}"
    ns_b = f"backplane-test-b-{uuid.uuid4().hex[:8]}"
    try:
        set_secret(ns_a, "api_key", "value-a")
        set_secret(ns_b, "api_key", "value-b")
        assert get_secret(ns_a, "api_key") == "value-a"
        assert get_secret(ns_b, "api_key") == "value-b"
    finally:
        delete_secret(ns_a, "api_key")
        delete_secret(ns_b, "api_key")

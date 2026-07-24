"""Wire protocol for host<->plugin IPC.

JSON-framed over multiprocessing.connection's pipe transport -- using the
transport but never its default send()/recv() (which pickles), so neither
side ever has to trust arbitrary pickled bytes from the other, and every
message is trivially inspectable/loggable. This channel carries every
hotkey/tray/settings/notify call, so keeping it plain and legible matters.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def encode_message(message: Dict[str, Any]) -> bytes:
    return json.dumps(message).encode("utf-8")


def decode_message(data: bytes) -> Dict[str, Any]:
    return json.loads(data.decode("utf-8"))


def make_message(
    msg_type: str,
    payload: Optional[Dict[str, Any]] = None,
    msg_id: Optional[int] = None,
) -> Dict[str, Any]:
    return {"type": msg_type, "id": msg_id, "payload": payload or {}}

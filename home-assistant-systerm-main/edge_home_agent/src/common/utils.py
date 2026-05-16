"""Common helper functions."""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_json_loads(payload: bytes) -> dict[str, Any]:
    try:
        return json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def publish_with_constraints(
    client: Any,
    topic: str,
    payload: dict[str, Any],
    qos: int,
    drop_rate: float,
    max_delay_ms: int,
) -> bool:
    if drop_rate > 0 and random.random() < drop_rate:
        return False

    if max_delay_ms > 0:
        delay_s = random.uniform(0, max_delay_ms) / 1000.0
        time.sleep(delay_s)

    client.publish(topic, json.dumps(payload), qos=qos)
    return True

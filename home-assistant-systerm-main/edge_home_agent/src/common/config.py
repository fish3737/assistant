"""Configuration shared by all modules."""

from __future__ import annotations

import os


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = env_int("MQTT_PORT", 1883)
MQTT_KEEPALIVE = env_int("MQTT_KEEPALIVE", 30)
MQTT_QOS = env_int("MQTT_QOS", 1)

SENSOR_TOPIC_PREFIX = "home/sensors"
COMMAND_TOPIC_PREFIX = "home/commands"
DEVICE_STATE_TOPIC = "home/devices/state"
DEVICE_STATE_TOPIC_PREFIX = "home/devices"
AGENT_EVENTS_TOPIC = "home/agent/events"

NIGHT_LUX_THRESHOLD = env_float("NIGHT_LUX_THRESHOLD", 80.0)
BRIGHT_LUX_THRESHOLD = env_float("BRIGHT_LUX_THRESHOLD", 250.0)
HOT_TEMP_THRESHOLD = env_float("HOT_TEMP_THRESHOLD", 28.0)
NO_MOTION_AC_OFF_SEC = env_int("NO_MOTION_AC_OFF_SEC", 20)
COMMAND_COOLDOWN_SEC = env_int("COMMAND_COOLDOWN_SEC", 6)

DEFAULT_SENSOR_DROP_RATE = env_float("SENSOR_DROP_RATE", 0.0)
DEFAULT_SENSOR_DELAY_MS = env_int("SENSOR_DELAY_MS", 0)
DEFAULT_CMD_DROP_RATE = env_float("CMD_DROP_RATE", 0.0)
DEFAULT_CMD_DELAY_MS = env_int("CMD_DELAY_MS", 0)

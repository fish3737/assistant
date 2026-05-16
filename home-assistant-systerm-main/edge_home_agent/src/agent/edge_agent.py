"""Local edge agent: read sensor states, decide actions, issue control commands."""

from __future__ import annotations

import heapq
import json
import logging
import time
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

from src.common.config import (
    AGENT_EVENTS_TOPIC,
    BRIGHT_LUX_THRESHOLD,
    COMMAND_COOLDOWN_SEC,
    COMMAND_TOPIC_PREFIX,
    DEFAULT_CMD_DELAY_MS,
    DEFAULT_CMD_DROP_RATE,
    DEVICE_STATE_TOPIC,
    HOT_TEMP_THRESHOLD,
    MQTT_HOST,
    MQTT_KEEPALIVE,
    MQTT_PORT,
    MQTT_QOS,
    NIGHT_LUX_THRESHOLD,
    NO_MOTION_AC_OFF_SEC,
    SENSOR_TOPIC_PREFIX,
)
from src.common.utils import publish_with_constraints, safe_json_loads, utc_now_iso


@dataclass(order=True)
class Task:
    priority: int
    created_at: float
    device: str = field(compare=False)
    command: str = field(compare=False)
    reason: str = field(compare=False)


class EdgeAgent:
    def __init__(self, cmd_drop_rate: float, cmd_delay_ms: int) -> None:
        self.cmd_drop_rate = cmd_drop_rate
        self.cmd_delay_ms = cmd_delay_ms

        self.sensor_state: dict[str, object] = {
            "temperature": None,
            "door": False,
            "pir": False,
            "light": None,
        }
        self.device_state: dict[str, bool] = {
            "light": False,
            "ac": False,
            "alarm": False,
        }

        self.last_motion_at = time.time()
        self.last_command_at: dict[tuple[str, str], float] = {}
        self.pending_keys: set[tuple[str, str]] = set()
        self.task_queue: list[Task] = []

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="edge-agent",
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(
        self,
        client: mqtt.Client,
        _userdata: object,
        _connect_flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.value == 0:
            logging.info("Connected to MQTT broker.")
            client.subscribe(f"{SENSOR_TOPIC_PREFIX}/+", qos=MQTT_QOS)
            client.subscribe(DEVICE_STATE_TOPIC, qos=MQTT_QOS)
        else:
            logging.error("Failed to connect, code=%s", reason_code.value)

    def on_message(
        self,
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        payload = safe_json_loads(message.payload)
        if not payload:
            return

        if message.topic.startswith(f"{SENSOR_TOPIC_PREFIX}/"):
            sensor_name = message.topic.split("/")[-1]
            value = payload.get("value")
            self.sensor_state[sensor_name] = value
            if sensor_name == "pir" and bool(value):
                self.last_motion_at = time.time()
            logging.info("Sensor update: %s=%s", sensor_name, value)
            self.evaluate_rules()
            return

        if message.topic == DEVICE_STATE_TOPIC:
            device = payload.get("device")
            state = payload.get("state")
            if device in self.device_state and state in {"on", "off"}:
                self.device_state[device] = state == "on"
                logging.info("Device state sync: %s=%s", device, state)

    def enqueue_task(self, priority: int, device: str, command: str, reason: str) -> None:
        if device not in self.device_state:
            return

        desired_state = command == "on"
        if self.device_state[device] == desired_state:
            return

        key = (device, command)
        if key in self.pending_keys:
            return

        last_sent = self.last_command_at.get(key, 0.0)
        if time.time() - last_sent < COMMAND_COOLDOWN_SEC:
            return

        task = Task(
            priority=priority,
            created_at=time.time(),
            device=device,
            command=command,
            reason=reason,
        )
        heapq.heappush(self.task_queue, task)
        self.pending_keys.add(key)
        logging.info("Task enqueued p=%d device=%s cmd=%s", priority, device, command)

    def evaluate_rules(self) -> None:
        now = time.time()
        temperature = self._to_float(self.sensor_state.get("temperature"))
        lux = self._to_float(self.sensor_state.get("light"))
        door_open = bool(self.sensor_state.get("door"))
        motion = bool(self.sensor_state.get("pir"))
        no_motion_for = now - self.last_motion_at

        is_dark = lux is not None and lux <= NIGHT_LUX_THRESHOLD
        is_night = is_dark
        is_bright = lux is not None and lux >= BRIGHT_LUX_THRESHOLD

        if door_open and is_dark:
            self.enqueue_task(2, "light", "on", "door-open-dark")

        if is_bright:
            self.enqueue_task(3, "light", "off", "ambient-bright")

        if no_motion_for >= NO_MOTION_AC_OFF_SEC:
            self.enqueue_task(2, "ac", "off", "no-motion-timeout")

        if temperature is not None and temperature >= HOT_TEMP_THRESHOLD and motion:
            self.enqueue_task(3, "ac", "on", "hot-with-motion")

        if is_night and door_open and not motion:
            self.enqueue_task(1, "alarm", "on", "night-door-anomaly")

        if not door_open and motion:
            self.enqueue_task(2, "alarm", "off", "occupancy-confirmed")

    def dispatch_one_task(self) -> None:
        if not self.task_queue:
            return

        task = heapq.heappop(self.task_queue)
        self.pending_keys.discard((task.device, task.command))

        topic = f"{COMMAND_TOPIC_PREFIX}/{task.device}"
        payload = {
            "device": task.device,
            "command": task.command,
            "reason": task.reason,
            "priority": task.priority,
            "ts": utc_now_iso(),
        }
        ok = publish_with_constraints(
            client=self.client,
            topic=topic,
            payload=payload,
            qos=MQTT_QOS,
            drop_rate=self.cmd_drop_rate,
            max_delay_ms=self.cmd_delay_ms,
        )
        if not ok:
            logging.warning("Command dropped: device=%s command=%s", task.device, task.command)
            return

        self.last_command_at[(task.device, task.command)] = time.time()
        event_payload = {
            "event": "dispatch",
            "device": task.device,
            "command": task.command,
            "priority": task.priority,
            "reason": task.reason,
            "ts": utc_now_iso(),
        }
        self.client.publish(AGENT_EVENTS_TOPIC, json.dumps(event_payload), qos=MQTT_QOS)
        logging.info(
            "Dispatched command p=%d %s=%s (%s)",
            task.priority,
            task.device,
            task.command,
            task.reason,
        )

    @staticmethod
    def _to_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def run(self) -> None:
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
        self.client.loop_start()
        logging.info(
            "Edge agent started (cmd_drop=%.2f, cmd_delay_ms=%d).",
            self.cmd_drop_rate,
            self.cmd_delay_ms,
        )
        try:
            while True:
                self.evaluate_rules()
                self.dispatch_one_task()
                time.sleep(0.8)
        except KeyboardInterrupt:
            logging.info("Edge agent stopped.")
        finally:
            self.client.loop_stop()
            self.client.disconnect()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | agent  | %(message)s",
    )
    agent = EdgeAgent(
        cmd_drop_rate=max(0.0, min(1.0, DEFAULT_CMD_DROP_RATE)),
        cmd_delay_ms=max(0, DEFAULT_CMD_DELAY_MS),
    )
    agent.run()


if __name__ == "__main__":
    main()

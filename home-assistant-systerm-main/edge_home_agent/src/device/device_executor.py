"""Simulate smart-home device execution based on agent commands."""

from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from src.common.config import (
    COMMAND_TOPIC_PREFIX,
    DEVICE_STATE_TOPIC,
    DEVICE_STATE_TOPIC_PREFIX,
    MQTT_HOST,
    MQTT_KEEPALIVE,
    MQTT_PORT,
    MQTT_QOS,
)
from src.common.utils import utc_now_iso


class DeviceExecutor:
    def __init__(self) -> None:
        self.states = {
            "light": False,
            "ac": True,
            "alarm": False,
        }

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="device-executor",
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
            client.subscribe(f"{COMMAND_TOPIC_PREFIX}/+", qos=MQTT_QOS)
            for device in self.states:
                self.publish_state(device, reason="boot-sync", retain=True)
        else:
            logging.error("Failed to connect, code=%s", reason_code.value)

    def on_message(
        self,
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        topic_parts = message.topic.split("/")
        if len(topic_parts) < 3:
            return
        device = topic_parts[-1]
        if device not in self.states:
            return

        payload = {}
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = message.payload.decode("utf-8", errors="ignore").strip().lower()
            if raw in {"on", "off", "toggle"}:
                payload = {"command": raw}
        command = payload.get("command")
        reason = payload.get("reason", "rule-action")
        if command not in {"on", "off", "toggle"}:
            logging.warning("Ignore invalid command=%s for %s", command, device)
            return

        old_state = self.states[device]
        if command == "toggle":
            self.states[device] = not old_state
        else:
            self.states[device] = command == "on"

        if self.states[device] != old_state:
            logging.info(
                "Device %s state changed: %s -> %s",
                device,
                "on" if old_state else "off",
                "on" if self.states[device] else "off",
            )
        else:
            logging.info("Device %s unchanged (%s)", device, "on" if old_state else "off")
        self.publish_state(device, reason=reason)

    def publish_state(self, device: str, reason: str, retain: bool = False) -> None:
        state_text = "on" if self.states[device] else "off"
        payload = {
            "device": device,
            "state": state_text,
            "reason": reason,
            "ts": utc_now_iso(),
        }
        self.client.publish(
            DEVICE_STATE_TOPIC,
            json.dumps(payload),
            qos=MQTT_QOS,
            retain=retain,
        )
        self.client.publish(
            f"{DEVICE_STATE_TOPIC_PREFIX}/{device}/state",
            state_text,
            qos=MQTT_QOS,
            retain=True,
        )

    def run(self) -> None:
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
        self.client.loop_forever()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | device | %(message)s",
    )
    executor = DeviceExecutor()
    try:
        executor.run()
    except KeyboardInterrupt:
        logging.info("Device executor stopped.")
    finally:
        executor.client.disconnect()


if __name__ == "__main__":
    main()

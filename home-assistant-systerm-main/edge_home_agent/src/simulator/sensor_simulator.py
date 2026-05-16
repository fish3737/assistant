"""Simulate smart-home sensor data and publish via MQTT."""

from __future__ import annotations

import argparse
import logging
import math
import random
import time

import paho.mqtt.client as mqtt

from src.common.config import (
    DEVICE_STATE_TOPIC,
    DEFAULT_SENSOR_DELAY_MS,
    DEFAULT_SENSOR_DROP_RATE,
    MQTT_HOST,
    MQTT_KEEPALIVE,
    MQTT_PORT,
    MQTT_QOS,
    NIGHT_LUX_THRESHOLD,
    SENSOR_TOPIC_PREFIX,
)
from src.common.utils import publish_with_constraints, safe_json_loads, utc_now_iso


class SensorSimulator:
    def __init__(
        self,
        interval_sec: float,
        drop_rate: float,
        delay_ms: int,
        seed: int | None,
    ) -> None:
        self.interval_sec = interval_sec
        self.drop_rate = drop_rate
        self.delay_ms = delay_ms
        self.rand = random.Random(seed)

        self.temperature_c = 25.0
        self.door_open = False
        self.motion_until = time.time() + 2
        self.door_close_at = time.time() + 1
        self.illuminance_lux = 350.0
        self.day_cycle_sec = 180.0

        self.ac_on = True
        self.light_on = False

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="sensor-simulator",
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
            client.subscribe(DEVICE_STATE_TOPIC, qos=MQTT_QOS)
        else:
            logging.error("Failed to connect, code=%s", reason_code.value)

    def on_message(
        self,
        _client: mqtt.Client,
        _userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        if message.topic != DEVICE_STATE_TOPIC:
            return

        payload = safe_json_loads(message.payload)
        device = payload.get("device")
        state = payload.get("state")
        if device == "ac":
            self.ac_on = state == "on"
        elif device == "light":
            self.light_on = state == "on"

    def update_world(self) -> None:
        now = time.time()

        phase = 2 * math.pi * ((now % self.day_cycle_sec) / self.day_cycle_sec)
        base_lux = max(8.0, 520.0 * max(0.0, math.sin(phase)))
        if self.light_on and base_lux <= NIGHT_LUX_THRESHOLD:
            base_lux += 180.0
        self.illuminance_lux = max(0.0, base_lux + self.rand.uniform(-8.0, 8.0))

        if not self.door_open and self.rand.random() < 0.05:
            self.door_open = True
            self.door_close_at = now + self.rand.uniform(2.0, 5.0)
            self.motion_until = max(self.motion_until, now + self.rand.uniform(8.0, 12.0))
        elif self.door_open and now >= self.door_close_at:
            self.door_open = False

        if self.rand.random() < 0.10:
            self.motion_until = max(self.motion_until, now + self.rand.uniform(2.0, 8.0))
        motion = now <= self.motion_until

        target_temp = 27.0 if self.illuminance_lux > NIGHT_LUX_THRESHOLD else 23.0
        if self.ac_on:
            target_temp -= 4.0
        if motion:
            target_temp += 0.4
        self.temperature_c += (target_temp - self.temperature_c) * 0.12
        self.temperature_c += self.rand.uniform(-0.25, 0.25)

        self.publish_sensor("temperature", round(self.temperature_c, 2), "C")
        self.publish_sensor("door", self.door_open, "bool")
        self.publish_sensor("pir", motion, "bool")
        self.publish_sensor("light", round(self.illuminance_lux, 1), "lux")

    def publish_sensor(self, sensor_name: str, value: object, unit: str) -> None:
        topic = f"{SENSOR_TOPIC_PREFIX}/{sensor_name}"
        payload = {
            "sensor": sensor_name,
            "value": value,
            "unit": unit,
            "ts": utc_now_iso(),
        }
        ok = publish_with_constraints(
            client=self.client,
            topic=topic,
            payload=payload,
            qos=MQTT_QOS,
            drop_rate=self.drop_rate,
            max_delay_ms=self.delay_ms,
        )
        if ok:
            logging.info("Published sensor=%s value=%s", sensor_name, value)
        else:
            logging.warning("Dropped sensor message: %s", sensor_name)

    def run(self) -> None:
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
        self.client.loop_start()
        logging.info(
            "Sensor simulator started (interval=%.1fs, drop=%.2f, delay_ms=%d).",
            self.interval_sec,
            self.drop_rate,
            self.delay_ms,
        )
        try:
            while True:
                self.update_world()
                time.sleep(self.interval_sec)
        except KeyboardInterrupt:
            logging.info("Sensor simulator stopped.")
        finally:
            self.client.loop_stop()
            self.client.disconnect()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smart-home sensor simulator.")
    parser.add_argument("--interval", type=float, default=1.5, help="Publish interval seconds.")
    parser.add_argument("--drop-rate", type=float, default=DEFAULT_SENSOR_DROP_RATE, help="Drop rate.")
    parser.add_argument("--delay-ms", type=int, default=DEFAULT_SENSOR_DELAY_MS, help="Max delay ms.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | sensor | %(message)s",
    )
    args = parse_args()
    simulator = SensorSimulator(
        interval_sec=args.interval,
        drop_rate=max(0.0, min(1.0, args.drop_rate)),
        delay_ms=max(0, args.delay_ms),
        seed=args.seed,
    )
    simulator.run()


if __name__ == "__main__":
    main()

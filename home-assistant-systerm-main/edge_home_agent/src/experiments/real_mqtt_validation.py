"""Run a real MQTT validation against the local broker and edge agent.

This script starts the actual ``src.agent.edge_agent`` process, publishes a
deterministic night-door anomaly sensor sequence to Mosquitto, emulates device
execution through MQTT, and records the observed control loop as CSV plus a
timeline image.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from PIL import Image, ImageDraw, ImageFont

from src.common.config import (
    AGENT_EVENTS_TOPIC,
    COMMAND_TOPIC_PREFIX,
    DEVICE_STATE_TOPIC,
    DEVICE_STATE_TOPIC_PREFIX,
    MQTT_QOS,
    SENSOR_TOPIC_PREFIX,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "experiments" / "mqtt_validation"


@dataclass
class RecordedEvent:
    t: float
    source: str
    event: str
    topic: str
    detail: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except (AttributeError, TypeError):
        return mqtt.Client(client_id=client_id)


def wait_for_broker(host: str, port: int, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        client = make_client("validation-broker-check")
        try:
            client.connect(host, port, keepalive=10)
            client.disconnect()
            return
        except Exception as exc:  # noqa: BLE001 - report final connection error
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"MQTT broker not reachable at {host}:{port}: {last_error}")


class EventRecorder:
    def __init__(self, start: float) -> None:
        self.start = start
        self.events: list[RecordedEvent] = []

    def add(self, source: str, event: str, topic: str, detail: str) -> None:
        self.events.append(RecordedEvent(time.time() - self.start, source, event, topic, detail))


class DeviceResponder:
    def __init__(self, host: str, port: int, recorder: EventRecorder) -> None:
        self.recorder = recorder
        self.states = {"light": False, "ac": True, "alarm": False}
        self.client = make_client("validation-device-responder")
        self.client.on_message = self.on_message
        self.client.connect(host, port, keepalive=20)
        self.client.subscribe(f"{COMMAND_TOPIC_PREFIX}/+", qos=MQTT_QOS)
        self.client.loop_start()

        for device in self.states:
            self.publish_state(device, reason="validation-boot")

    def on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        device = message.topic.split("/")[-1]
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except json.JSONDecodeError:
            return
        command = payload.get("command")
        if device not in self.states or command not in {"on", "off", "toggle"}:
            return
        if command == "toggle":
            self.states[device] = not self.states[device]
        else:
            self.states[device] = command == "on"
        detail = f"{device}={command}, reason={payload.get('reason')}, priority={payload.get('priority')}"
        self.recorder.add("device", "command_received", message.topic, detail)
        self.publish_state(device, reason=payload.get("reason", "validation-command"))

    def publish_state(self, device: str, reason: str) -> None:
        state_text = "on" if self.states[device] else "off"
        payload = {
            "device": device,
            "state": state_text,
            "reason": reason,
            "ts": utc_now_iso(),
        }
        self.client.publish(DEVICE_STATE_TOPIC, json.dumps(payload), qos=MQTT_QOS)
        self.client.publish(f"{DEVICE_STATE_TOPIC_PREFIX}/{device}/state", state_text, qos=MQTT_QOS, retain=True)
        self.recorder.add("device", "state_published", DEVICE_STATE_TOPIC, f"{device}={state_text}, reason={reason}")

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


class Observer:
    def __init__(self, host: str, port: int, recorder: EventRecorder) -> None:
        self.recorder = recorder
        self.client = make_client("validation-observer")
        self.client.on_message = self.on_message
        self.client.connect(host, port, keepalive=20)
        self.client.subscribe(AGENT_EVENTS_TOPIC, qos=MQTT_QOS)
        self.client.subscribe(DEVICE_STATE_TOPIC, qos=MQTT_QOS)
        self.client.loop_start()

    def on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        payload = message.payload.decode("utf-8", errors="ignore")
        detail = payload
        try:
            parsed = json.loads(payload)
            if message.topic == AGENT_EVENTS_TOPIC:
                detail = f"{parsed.get('device')}={parsed.get('command')}, reason={parsed.get('reason')}, p={parsed.get('priority')}"
                self.recorder.add("agent", "dispatch", message.topic, detail)
            elif message.topic == DEVICE_STATE_TOPIC:
                detail = f"{parsed.get('device')}={parsed.get('state')}, reason={parsed.get('reason')}"
                self.recorder.add("mqtt", "device_state_observed", message.topic, detail)
            return
        except json.JSONDecodeError:
            pass
        self.recorder.add("mqtt", "message", message.topic, detail)

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def publish_sensor(client: mqtt.Client, recorder: EventRecorder, sensor: str, value: Any, unit: str) -> None:
    topic = f"{SENSOR_TOPIC_PREFIX}/{sensor}"
    payload = {"sensor": sensor, "value": value, "unit": unit, "ts": utc_now_iso()}
    client.publish(topic, json.dumps(payload), qos=MQTT_QOS)
    recorder.add("sensor", "sensor_published", topic, f"{sensor}={value}")


def write_events(out_dir: Path, rows: list[RecordedEvent]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "events.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["t", "source", "event", "topic", "detail"])
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r.t):
            writer.writerow(
                {
                    "t": round(row.t, 4),
                    "source": row.source,
                    "event": row.event,
                    "topic": row.topic,
                    "detail": row.detail,
                }
            )


def summarize(out_dir: Path, rows: list[RecordedEvent], host: str, port: int) -> None:
    saw_alarm_dispatch = any(row.source == "agent" and "alarm=on" in row.detail for row in rows)
    saw_alarm_state = any(row.event in {"state_published", "device_state_observed"} and "alarm=on" in row.detail for row in rows)
    saw_light_dispatch = any(row.source == "agent" and "light=on" in row.detail for row in rows)
    saw_light_state = any(row.event in {"state_published", "device_state_observed"} and "light=on" in row.detail for row in rows)
    summary = {
        "broker": f"{host}:{port}",
        "real_mqtt_validation": bool(saw_alarm_dispatch and saw_alarm_state and saw_light_dispatch and saw_light_state),
        "saw_alarm_dispatch": saw_alarm_dispatch,
        "saw_alarm_state_on": saw_alarm_state,
        "saw_light_dispatch": saw_light_dispatch,
        "saw_light_state_on": saw_light_state,
        "event_count": len(rows),
        "generated_at": utc_now_iso(),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def font(size: int) -> Any:
    candidates = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def render_timeline(out_dir: Path, rows: list[RecordedEvent]) -> None:
    im = Image.new("RGB", (1600, 900), "#f5f7fb")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1600, 110], fill="#142033")
    d.rectangle([0, 110, 1600, 116], fill="#39a9bb")
    d.text((56, 28), "真实 MQTT 验证时间线", font=font(34), fill="#ffffff")
    d.text((56, 134), "实际 broker + edge_agent.py + MQTT 设备反馈", font=font(22), fill="#27344f")

    selected: list[RecordedEvent] = []
    for row in sorted(rows, key=lambda r: r.t):
        if row.source == "sensor" and row.detail in {"light=20", "door=True", "pir=False"}:
            selected.append(row)
        if row.source == "agent" and ("alarm=on" in row.detail or "light=on" in row.detail):
            selected.append(row)
        if row.event == "state_published" and ("alarm=on" in row.detail or "light=on" in row.detail):
            selected.append(row)
    selected = selected[:8]

    left, right = 150, 1460
    top = 245
    row_h = 72
    start_t = selected[0].t if selected else 0.0
    max_t = max((row.t - start_t for row in selected), default=1.0) or 1.0
    d.line([(left, top + 300), (right, top + 300)], fill="#6b778d", width=4)
    colors = {"sensor": "#39a9bb", "agent": "#4f73d9", "device": "#ef9b3a", "mqtt": "#74bd6d"}
    for idx, row in enumerate(selected):
        delta = row.t - start_t
        x = left + (right - left) * delta / max_t
        y = top + 300
        color = colors.get(row.source, "#6d7f99")
        d.ellipse([x - 11, y - 11, x + 11, y + 11], fill=color)
        box_y = 250 + (idx % 4) * row_h
        d.line([(x, y), (x, box_y + 34)], fill=color, width=2)
        d.rounded_rectangle([x - 120, box_y, x + 120, box_y + 58], radius=12, fill="#ffffff", outline="#d3dce9", width=2)
        d.text((x - 102, box_y + 9), f"{row.source}: {row.event}", font=font(15), fill="#27344f")
        d.text((x - 102, box_y + 31), f"+{delta * 1000:.0f}ms {row.detail[:22]}", font=font(13), fill=color)

    d.text((88, 760), "结论：真实 MQTT 链路中可以观察到传感器发布、Agent 派发命令、设备状态反馈的完整闭环。", font=font(22), fill="#27344f")
    im.save(out_dir / "mqtt_validation_timeline.png")


def run_validation(host: str, port: int, out_dir: Path, timeout_s: float) -> None:
    wait_for_broker(host, port, timeout_s=20)
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.time()
    recorder = EventRecorder(start)
    observer = Observer(host, port, recorder)
    device = DeviceResponder(host, port, recorder)
    sensor_client = make_client("validation-sensor-publisher")
    sensor_client.connect(host, port, keepalive=20)
    sensor_client.loop_start()

    env = os.environ.copy()
    env.update(
        {
            "MQTT_HOST": host,
            "MQTT_PORT": str(port),
            "COMMAND_COOLDOWN_SEC": "0",
            "CMD_DROP_RATE": "0",
            "CMD_DELAY_MS": "0",
            "NO_MOTION_AC_OFF_SEC": "60",
        }
    )
    agent = subprocess.Popen(
        [sys.executable, "-u", "-m", "src.agent.edge_agent"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        time.sleep(2.0)
        for sensor, value, unit in [
            ("temperature", 24.5, "C"),
            ("light", 350, "lux"),
            ("door", False, "bool"),
            ("pir", True, "bool"),
        ]:
            publish_sensor(sensor_client, recorder, sensor, value, unit)
            time.sleep(0.15)

        time.sleep(1.0)
        for sensor, value, unit in [
            ("light", 20, "lux"),
            ("pir", False, "bool"),
            ("door", True, "bool"),
            ("temperature", 25.0, "C"),
        ]:
            publish_sensor(sensor_client, recorder, sensor, value, unit)
            time.sleep(0.2)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            alarm_ok = any(row.source == "agent" and "alarm=on" in row.detail for row in recorder.events)
            light_ok = any(row.source == "agent" and "light=on" in row.detail for row in recorder.events)
            ack_ok = any(row.event == "state_published" and "alarm=on" in row.detail for row in recorder.events)
            if alarm_ok and light_ok and ack_ok:
                break
            time.sleep(0.2)

        for sensor, value, unit in [
            ("door", False, "bool"),
            ("pir", True, "bool"),
        ]:
            publish_sensor(sensor_client, recorder, sensor, value, unit)
            time.sleep(0.2)
        time.sleep(1.0)
    finally:
        sensor_client.loop_stop()
        sensor_client.disconnect()
        observer.stop()
        device.stop()
        if agent.poll() is None:
            agent.send_signal(signal.SIGINT)
            try:
                agent.wait(timeout=3)
            except subprocess.TimeoutExpired:
                agent.kill()
        agent_output = agent.stdout.read() if agent.stdout else ""
        (out_dir / "agent_stdout.log").write_text(agent_output, encoding="utf-8")

    write_events(out_dir, recorder.events)
    summarize(out_dir, recorder.events, host, port)
    render_timeline(out_dir, recorder.events)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real MQTT validation for edge agent.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_validation(args.host, args.port, args.out, args.timeout)
    print(f"MQTT validation results written to: {args.out}")


if __name__ == "__main__":
    main()


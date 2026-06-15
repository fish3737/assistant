"""Run repeatable edge-agent experiments and generate result charts.

The experiments use a virtual-time simulation of the same smart-home control
loop used by the MQTT demo: sensor updates, network constraints, agent task
generation, device execution, and device-state acknowledgement. This keeps the
results reproducible while still measuring real executions of the control logic
under latency, packet loss, and device-offline conditions.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - handled in CLI
    Image = None
    ImageDraw = None
    ImageFont = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "experiments" / "results"

SENSOR_INTERVAL_S = 1.0
AGENT_TICK_S = 0.5
DISPATCH_INTERVAL_S = 0.8
COMMAND_COOLDOWN_S = 2.0
NO_MOTION_AC_OFF_S = 16.0
NIGHT_LUX_THRESHOLD = 80.0
BRIGHT_LUX_THRESHOLD = 250.0
HOT_TEMP_THRESHOLD = 28.0

MODE_LABELS = {
    "fifo_rule": "普通规则",
    "priority": "优先级调度",
    "priority_stale": "优先级+过期",
    "priority_retry": "优先级+重试",
    "fault_tolerant": "容错 Agent",
}
MODE_ORDER = ["fifo_rule", "priority", "fault_tolerant"]
ABLATION_ORDER = ["fifo_rule", "priority", "priority_stale", "priority_retry", "fault_tolerant"]


@dataclass(order=True)
class Event:
    at: float
    seq: int
    kind: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False, default_factory=dict)


@dataclass
class Task:
    task_id: int
    run_id: int
    mode: str
    experiment: str
    latency_ms: int
    drop_rate: float
    offline_rate: float
    scenario_id: str
    device: str
    command: str
    reason: str
    priority: int
    created_at: float
    attempts: int = 0
    first_dispatch_at: float | None = None
    completed_at: float | None = None
    failed_at: float | None = None
    status: str = "queued"

    @property
    def queue_wait_ms(self) -> float | None:
        if self.first_dispatch_at is None:
            return None
        return (self.first_dispatch_at - self.created_at) * 1000.0

    @property
    def response_ms(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.created_at) * 1000.0


class EventBus:
    def __init__(self) -> None:
        self._heap: list[Event] = []
        self._seq = 0

    def schedule(self, at: float, kind: str, payload: dict[str, Any] | None = None) -> None:
        self._seq += 1
        heapq.heappush(self._heap, Event(at, self._seq, kind, payload or {}))

    def pop(self) -> Event | None:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)


class Network:
    def __init__(self, rng: random.Random, latency_ms: int, drop_rate: float) -> None:
        self.rng = rng
        self.latency_ms = latency_ms
        self.drop_rate = drop_rate

    def latency_s(self) -> float:
        if self.latency_ms <= 0:
            return 0.0
        return self.rng.uniform(0.0, self.latency_ms) / 1000.0

    def deliver(self, bus: EventBus, now: float, kind: str, payload: dict[str, Any], drop_scale: float = 1.0) -> bool:
        drop = min(1.0, max(0.0, self.drop_rate * drop_scale))
        if drop > 0 and self.rng.random() < drop:
            return False
        bus.schedule(now + self.latency_s(), kind, payload)
        return True


class SmartHomeWorld:
    def __init__(self, horizon_s: int) -> None:
        self.horizon_s = horizon_s
        self.alarm_windows: list[tuple[float, float, str]] = []
        start = 18.0
        idx = 1
        while start < horizon_s - 15:
            self.alarm_windows.append((start, start + 5.0, f"alarm_{idx:02d}"))
            start += 42.0
            idx += 1

    def alarm_opportunities(self, run_id: int, experiment: str, mode: str, latency_ms: int, drop_rate: float, offline_rate: float) -> list[dict[str, Any]]:
        return [
            {
                "run_id": run_id,
                "experiment": experiment,
                "mode": mode,
                "latency_ms": latency_ms,
                "drop_rate": drop_rate,
                "offline_rate": offline_rate,
                "scenario_id": scenario_id,
                "start_at": start,
                "end_at": end,
            }
            for start, end, scenario_id in self.alarm_windows
        ]

    def snapshot(self, t: float) -> dict[str, Any]:
        alarm_id = ""
        door_open = False
        motion = (t % 48.0) < 13.0
        lux = 340.0 if (int(t // 70.0) % 2 == 1) else 35.0

        for start, end, scenario_id in self.alarm_windows:
            if start <= t < end:
                alarm_id = scenario_id
                door_open = True
                motion = False
                lux = 25.0
                break
            if end <= t < end + 8.0:
                door_open = False
                motion = True
                lux = 45.0

        if not alarm_id and int(t) % 58 in {7, 8, 9, 10}:
            door_open = True
            lux = min(lux, 55.0)
            motion = True

        temp = 25.8 + 2.3 * math.sin(t / 18.0)
        if motion and int(t // 36.0) % 2 == 0:
            temp += 1.4
        if lux > BRIGHT_LUX_THRESHOLD:
            temp += 0.8

        return {
            "temperature": round(temp, 2),
            "door": door_open,
            "pir": motion,
            "light": round(lux, 1),
            "alarm_id": alarm_id,
        }


class SimulatedDevice:
    def __init__(self, rng: random.Random, network: Network, bus: EventBus, offline_rate: float) -> None:
        self.rng = rng
        self.network = network
        self.bus = bus
        self.offline_rate = offline_rate
        self.states = {"light": False, "ac": True, "alarm": False}

    def on_command(self, now: float, payload: dict[str, Any]) -> None:
        if self.offline_rate > 0 and self.rng.random() < self.offline_rate:
            return

        device = payload["device"]
        command = payload["command"]
        if command == "toggle":
            self.states[device] = not self.states[device]
        else:
            self.states[device] = command == "on"

        ack = {
            "task_id": payload["task_id"],
            "device": device,
            "state": "on" if self.states[device] else "off",
            "attempt": payload["attempt"],
        }
        self.network.deliver(self.bus, now + 0.05, "device_ack", ack, drop_scale=0.45)


class SimulatedAgent:
    def __init__(
        self,
        mode: str,
        network: Network,
        bus: EventBus,
        experiment: str,
        run_id: int,
        latency_ms: int,
        drop_rate: float,
        offline_rate: float,
    ) -> None:
        self.mode = mode
        self.network = network
        self.bus = bus
        self.experiment = experiment
        self.run_id = run_id
        self.latency_ms = latency_ms
        self.drop_rate = drop_rate
        self.offline_rate = offline_rate

        self.use_priority = mode in {"priority", "priority_stale", "priority_retry", "fault_tolerant"}
        self.use_stale_guard = mode in {"priority_stale", "fault_tolerant"}
        self.retry_limit = 2 if mode in {"priority_retry", "fault_tolerant"} else 0
        self.sensor_ttl_s = 3.2
        self.ack_timeout_s = 1.8 + (2 * latency_ms / 1000.0)

        self.sensor_values: dict[str, Any] = {}
        self.sensor_seen_at: dict[str, float] = {}
        self.latest_alarm_id = ""
        self.device_state = {"light": False, "ac": True, "alarm": False}
        self.last_motion_at = 0.0
        self.last_dispatch_at = -999.0
        self.last_command_at: dict[tuple[str, str], float] = {}
        self.active_keys: set[tuple[str, str]] = set()
        self.task_seq = 0
        self.task_heap: list[tuple[float, float, int, int]] = []
        self.tasks: dict[int, Task] = {}
        self.stale_skips = 0

    def on_sensor(self, now: float, payload: dict[str, Any]) -> None:
        sensor = payload["sensor"]
        self.sensor_values[sensor] = payload["value"]
        self.sensor_seen_at[sensor] = now
        if payload.get("alarm_id"):
            self.latest_alarm_id = str(payload["alarm_id"])
        if sensor == "pir" and bool(payload["value"]):
            self.last_motion_at = now
        self.evaluate(now)

    def on_ack(self, now: float, payload: dict[str, Any]) -> None:
        device = payload["device"]
        state = payload["state"]
        self.device_state[device] = state == "on"

        task = self.tasks.get(int(payload["task_id"]))
        if not task or task.status == "success":
            return
        if task.device == device and task.command == state:
            task.status = "success"
            task.completed_at = now
            self.active_keys.discard((task.device, task.command))

    def on_timeout(self, now: float, payload: dict[str, Any]) -> None:
        task = self.tasks.get(int(payload["task_id"]))
        if not task or task.status == "success":
            return
        if task.attempts <= self.retry_limit:
            task.status = "queued"
            self._push_task(task, now, retry=True)
            return
        task.status = "failed"
        task.failed_at = now
        self.active_keys.discard((task.device, task.command))

    def evaluate(self, now: float) -> None:
        temperature = self._sensor_float("temperature", now)
        lux = self._sensor_float("light", now)
        door_open = self._sensor_bool("door", now)
        motion = self._sensor_bool("pir", now)

        is_dark = lux is not None and lux <= NIGHT_LUX_THRESHOLD
        is_bright = lux is not None and lux >= BRIGHT_LUX_THRESHOLD

        if door_open is True and is_dark:
            self.enqueue(now, 2, "light", "on", "door-open-dark", self.latest_alarm_id)

        if is_bright:
            self.enqueue(now, 3, "light", "off", "ambient-bright", "")

        if motion is False and now - self.last_motion_at >= NO_MOTION_AC_OFF_S:
            self.enqueue(now, 2, "ac", "off", "no-motion-timeout", "")

        if temperature is not None and temperature >= HOT_TEMP_THRESHOLD and motion is True:
            self.enqueue(now, 3, "ac", "on", "hot-with-motion", "")

        if door_open is True and is_dark and motion is False:
            self.enqueue(now, 1, "alarm", "on", "night-door-anomaly", self.latest_alarm_id)

        if door_open is False and motion is True:
            self.enqueue(now, 2, "alarm", "off", "occupancy-confirmed", self.latest_alarm_id)

    def dispatch_if_ready(self, now: float) -> None:
        if now - self.last_dispatch_at < DISPATCH_INTERVAL_S:
            return
        if not self.task_heap:
            return

        _, _, _, task_id = heapq.heappop(self.task_heap)
        task = self.tasks[task_id]
        if task.status != "queued":
            return

        task.status = "dispatched"
        task.attempts += 1
        if task.first_dispatch_at is None:
            task.first_dispatch_at = now
        self.last_dispatch_at = now
        self.last_command_at[(task.device, task.command)] = now

        command_payload = {
            "task_id": task.task_id,
            "device": task.device,
            "command": task.command,
            "reason": task.reason,
            "priority": task.priority,
            "attempt": task.attempts,
        }
        self.network.deliver(self.bus, now, "device_command", command_payload)
        self.bus.schedule(now + self.ack_timeout_s, "ack_timeout", {"task_id": task.task_id})

    def enqueue(
        self,
        now: float,
        priority: int,
        device: str,
        command: str,
        reason: str,
        scenario_id: str,
    ) -> None:
        desired = command == "on"
        if self.device_state.get(device) == desired:
            return
        key = (device, command)
        if key in self.active_keys:
            return
        if now - self.last_command_at.get(key, -999.0) < COMMAND_COOLDOWN_S:
            return

        self.task_seq += 1
        task = Task(
            task_id=self.task_seq,
            run_id=self.run_id,
            mode=self.mode,
            experiment=self.experiment,
            latency_ms=self.latency_ms,
            drop_rate=self.drop_rate,
            offline_rate=self.offline_rate,
            scenario_id=scenario_id,
            device=device,
            command=command,
            reason=reason,
            priority=priority,
            created_at=now,
        )
        self.tasks[task.task_id] = task
        self.active_keys.add(key)
        self._push_task(task, now)

    def _push_task(self, task: Task, now: float, retry: bool = False) -> None:
        if retry and self.mode in {"priority_retry", "fault_tolerant"} and task.reason == "night-door-anomaly":
            task.priority = 0
        order_priority = task.priority if self.use_priority else 10
        heapq.heappush(self.task_heap, (order_priority, now if retry else task.created_at, task.attempts, task.task_id))

    def _sensor_fresh(self, sensor: str, now: float) -> bool:
        if sensor not in self.sensor_seen_at:
            return False
        if not self.use_stale_guard:
            return True
        fresh = now - self.sensor_seen_at[sensor] <= self.sensor_ttl_s
        if not fresh:
            self.stale_skips += 1
        return fresh

    def _sensor_float(self, sensor: str, now: float) -> float | None:
        if not self._sensor_fresh(sensor, now):
            return None
        try:
            return float(self.sensor_values.get(sensor))
        except (TypeError, ValueError):
            return None

    def _sensor_bool(self, sensor: str, now: float) -> bool | None:
        if not self._sensor_fresh(sensor, now):
            return None
        if sensor not in self.sensor_values:
            return None
        return bool(self.sensor_values[sensor])

    def finalize(self, end_at: float) -> None:
        for task in self.tasks.values():
            if task.status != "success" and task.status != "failed":
                task.status = "failed"
                task.failed_at = end_at
                self.active_keys.discard((task.device, task.command))


class Simulation:
    def __init__(
        self,
        experiment: str,
        run_id: int,
        mode: str,
        latency_ms: int,
        drop_rate: float,
        offline_rate: float,
        horizon_s: int,
        seed: int,
    ) -> None:
        self.experiment = experiment
        self.run_id = run_id
        self.mode = mode
        self.latency_ms = latency_ms
        self.drop_rate = drop_rate
        self.offline_rate = offline_rate
        self.horizon_s = horizon_s
        self.rng = random.Random(seed)
        self.bus = EventBus()
        self.network = Network(self.rng, latency_ms, drop_rate)
        self.world = SmartHomeWorld(horizon_s)
        self.agent = SimulatedAgent(
            mode=mode,
            network=self.network,
            bus=self.bus,
            experiment=experiment,
            run_id=run_id,
            latency_ms=latency_ms,
            drop_rate=drop_rate,
            offline_rate=offline_rate,
        )
        self.device = SimulatedDevice(self.rng, self.network, self.bus, offline_rate)

    def run(self) -> tuple[list[Task], list[dict[str, Any]], int]:
        self._schedule_world()
        end_at = self.horizon_s + 8.0 + self.latency_ms / 500.0

        while True:
            event = self.bus.pop()
            if event is None or event.at > end_at:
                break
            now = event.at
            if event.kind == "sensor":
                self.agent.on_sensor(now, event.payload)
            elif event.kind == "agent_tick":
                self.agent.evaluate(now)
                self.agent.dispatch_if_ready(now)
            elif event.kind == "device_command":
                self.device.on_command(now, event.payload)
            elif event.kind == "device_ack":
                self.agent.on_ack(now, event.payload)
            elif event.kind == "ack_timeout":
                self.agent.on_timeout(now, event.payload)

        self.agent.finalize(end_at)
        opportunities = self.world.alarm_opportunities(
            run_id=self.run_id,
            experiment=self.experiment,
            mode=self.mode,
            latency_ms=self.latency_ms,
            drop_rate=self.drop_rate,
            offline_rate=self.offline_rate,
        )
        return list(self.agent.tasks.values()), opportunities, self.agent.stale_skips

    def _schedule_world(self) -> None:
        t = 0.0
        while t <= self.horizon_s:
            snapshot = self.world.snapshot(t)
            for sensor in ("temperature", "door", "pir", "light"):
                payload = {
                    "sensor": sensor,
                    "value": snapshot[sensor],
                    "source_ts": t,
                    "alarm_id": snapshot["alarm_id"],
                }
                self.network.deliver(self.bus, t, "sensor", payload)
            self.bus.schedule(t, "agent_tick")
            t += SENSOR_INTERVAL_S


def task_to_row(task: Task) -> dict[str, Any]:
    return {
        "experiment": task.experiment,
        "run_id": task.run_id,
        "mode": task.mode,
        "mode_label": MODE_LABELS[task.mode],
        "latency_ms": task.latency_ms,
        "drop_rate": task.drop_rate,
        "offline_rate": task.offline_rate,
        "task_id": task.task_id,
        "scenario_id": task.scenario_id,
        "device": task.device,
        "command": task.command,
        "reason": task.reason,
        "priority": task.priority,
        "created_at": round(task.created_at, 4),
        "first_dispatch_at": round(task.first_dispatch_at, 4) if task.first_dispatch_at is not None else "",
        "completed_at": round(task.completed_at, 4) if task.completed_at is not None else "",
        "failed_at": round(task.failed_at, 4) if task.failed_at is not None else "",
        "status": task.status,
        "attempts": task.attempts,
        "queue_wait_ms": round(task.queue_wait_ms, 2) if task.queue_wait_ms is not None else "",
        "response_ms": round(task.response_ms, 2) if task.response_ms is not None else "",
    }


def run_suite(out_dir: Path, horizon_s: int, reps: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    all_tasks: list[Task] = []
    all_opportunities: list[dict[str, Any]] = []
    stale_rows: list[dict[str, Any]] = []
    run_counter = 0

    def one(experiment: str, mode: str, latency_ms: int, drop_rate: float, offline_rate: float, local_reps: int) -> None:
        nonlocal run_counter
        for rep in range(local_reps):
            run_counter += 1
            seed = 20260613 + run_counter * 97
            sim = Simulation(
                experiment=experiment,
                run_id=run_counter,
                mode=mode,
                latency_ms=latency_ms,
                drop_rate=drop_rate,
                offline_rate=offline_rate,
                horizon_s=horizon_s,
                seed=seed,
            )
            tasks, opportunities, stale_skips = sim.run()
            all_tasks.extend(tasks)
            all_opportunities.extend(opportunities)
            stale_rows.append(
                {
                    "experiment": experiment,
                    "run_id": run_counter,
                    "mode": mode,
                    "latency_ms": latency_ms,
                    "drop_rate": drop_rate,
                    "offline_rate": offline_rate,
                    "stale_skips": stale_skips,
                }
            )

    for latency in [0, 100, 200, 500, 800]:
        one("latency_response", "fault_tolerant", latency, 0.05, 0.02, reps)

    for drop in [0.0, 0.05, 0.10, 0.20, 0.30, 0.40]:
        one("drop_success", "fault_tolerant", 200, drop, 0.02, reps)

    for mode in MODE_ORDER:
        one("mode_comparison", mode, 300, 0.15, 0.08, reps + 2)

    for mode in MODE_ORDER:
        one("alarm_reliability", mode, 350, 0.20, 0.10, reps + 2)

    for mode in ABLATION_ORDER:
        one("ablation", mode, 350, 0.20, 0.10, reps + 2)

    task_rows = [task_to_row(task) for task in all_tasks]
    write_csv(out_dir / "tasks.csv", task_rows)
    write_csv(out_dir / "alarm_opportunities.csv", all_opportunities)
    write_csv(out_dir / "stale_state_events.csv", stale_rows)

    summary = summarize(task_rows, all_opportunities, stale_rows)
    write_csv(out_dir / "summary.csv", summary)

    metadata = {
        "horizon_s": horizon_s,
        "base_repetitions": reps,
        "total_runs": run_counter,
        "total_tasks": len(task_rows),
        "experiments": [
            "latency_response",
            "drop_success",
            "mode_comparison",
            "alarm_reliability",
            "ablation",
        ],
        "agent_modes": MODE_LABELS,
    }
    (out_dir / "experiment_config.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_charts(out_dir)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def summarize(
    task_rows: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    stale_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in task_rows:
        key = (
            row["experiment"],
            row["mode"],
            int(row["latency_ms"]),
            float(row["drop_rate"]),
            float(row["offline_rate"]),
        )
        groups[key].append(row)

    opp_groups: dict[tuple[Any, ...], set[tuple[int, str]]] = defaultdict(set)
    for row in opportunities:
        key = (
            row["experiment"],
            row["mode"],
            int(row["latency_ms"]),
            float(row["drop_rate"]),
            float(row["offline_rate"]),
        )
        opp_groups[key].add((int(row["run_id"]), row["scenario_id"]))

    stale_groups: dict[tuple[Any, ...], int] = defaultdict(int)
    for row in stale_rows:
        key = (
            row["experiment"],
            row["mode"],
            int(row["latency_ms"]),
            float(row["drop_rate"]),
            float(row["offline_rate"]),
        )
        stale_groups[key] += int(row["stale_skips"])

    summaries: list[dict[str, Any]] = []
    for key, rows in sorted(groups.items()):
        experiment, mode, latency_ms, drop_rate, offline_rate = key
        successes = [row for row in rows if row["status"] == "success"]
        responses = [float(row["response_ms"]) for row in successes if row["response_ms"] != ""]
        waits = [float(row["queue_wait_ms"]) for row in rows if row["queue_wait_ms"] != ""]
        attempts = [int(row["attempts"]) for row in rows]
        alarm_on_rows = [
            row
            for row in rows
            if row["device"] == "alarm" and row["command"] == "on" and row["reason"] == "night-door-anomaly"
        ]
        alarm_waits = [float(row["queue_wait_ms"]) for row in alarm_on_rows if row["queue_wait_ms"] != ""]
        alarm_responses = [
            float(row["response_ms"])
            for row in alarm_on_rows
            if row["status"] == "success" and row["response_ms"] != ""
        ]
        alarm_success_ids = {
            (int(row["run_id"]), row["scenario_id"])
            for row in successes
            if row["device"] == "alarm" and row["command"] == "on" and row["reason"] == "night-door-anomaly" and row["scenario_id"]
        }
        alarm_total = len(opp_groups.get(key, set()))
        alarm_success = len(alarm_success_ids)

        summaries.append(
            {
                "experiment": experiment,
                "mode": mode,
                "mode_label": MODE_LABELS[mode],
                "latency_ms": latency_ms,
                "drop_rate": drop_rate,
                "offline_rate": offline_rate,
                "total_tasks": len(rows),
                "successful_tasks": len(successes),
                "success_rate": round(safe_div(len(successes), len(rows)), 4),
                "avg_response_ms": round(mean(responses), 2),
                "median_response_ms": round(median(responses), 2),
                "avg_queue_wait_ms": round(mean(waits), 2),
                "p95_queue_wait_ms": round(percentile(waits, 0.95), 2),
                "alarm_opportunities": alarm_total,
                "alarm_success": alarm_success,
                "alarm_completion_rate": round(safe_div(alarm_success, alarm_total), 4),
                "alarm_miss_rate": round(1.0 - safe_div(alarm_success, alarm_total), 4),
                "alarm_avg_queue_wait_ms": round(mean(alarm_waits), 2),
                "alarm_avg_response_ms": round(mean(alarm_responses), 2),
                "avg_attempts": round(mean(attempts), 2),
                "stale_skips": stale_groups.get(key, 0),
            }
        )
    return summaries


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.mean(values) if values else 0.0


def median(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.median(values) if values else 0.0


def percentile(values: Iterable[float], q: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
    return values[idx]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def generate_charts(out_dir: Path) -> None:
    if PIL_IMPORT_ERROR is not None:
        raise RuntimeError("Pillow is required for chart generation. Install with: pip install pillow") from PIL_IMPORT_ERROR

    chart_dir = out_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    summary = read_csv(out_dir / "summary.csv")
    tasks = read_csv(out_dir / "tasks.csv")

    latency_rows = sorted(
        [r for r in summary if r["experiment"] == "latency_response"],
        key=lambda r: int(r["latency_ms"]),
    )
    line_chart(
        [(int(r["latency_ms"]), float(r["avg_response_ms"])) for r in latency_rows],
        title="不同网络延迟下的平均响应时间",
        subtitle="模式：容错 Agent；指标来自任务完成确认时间",
        x_label="最大网络延迟（ms）",
        y_label="平均响应时间（ms）",
        out=chart_dir / "01_avg_response_by_latency.png",
        color="#3aa6b9",
    )

    drop_rows = sorted(
        [r for r in summary if r["experiment"] == "drop_success"],
        key=lambda r: float(r["drop_rate"]),
    )
    line_chart(
        [(float(r["drop_rate"]) * 100, float(r["success_rate"]) * 100) for r in drop_rows],
        title="不同丢包率下的任务成功率",
        subtitle="模式：容错 Agent；含命令确认与失败重试",
        x_label="消息丢包率（%）",
        y_label="任务成功率（%）",
        out=chart_dir / "02_success_rate_by_drop.png",
        color="#6fbf73",
        y_max=100.0,
    )

    mode_rows = [r for r in summary if r["experiment"] == "mode_comparison"]
    grouped_bar_chart(
        mode_rows,
        title="普通规则 Agent vs 优先级 Agent vs 容错 Agent",
        subtitle="网络条件：300ms 延迟、15% 丢包、8% 设备离线",
        out=chart_dir / "03_agent_mode_comparison.png",
    )

    alarm_rows = sorted(
        [r for r in summary if r["experiment"] == "alarm_reliability"],
        key=lambda r: MODE_ORDER.index(r["mode"]),
    )
    simple_bar_chart(
        [(r["mode_label"], float(r["alarm_completion_rate"]) * 100) for r in alarm_rows],
        title="报警任务完成率对比",
        subtitle="异常场景：夜间开门且无人；网络条件更严格",
        x_label="Agent 模式",
        y_label="报警完成率（%）",
        out=chart_dir / "04_alarm_completion_rate.png",
        y_max=100.0,
        color="#ef9b3a",
    )

    distribution_rows = [r for r in tasks if r["experiment"] == "mode_comparison" and r["queue_wait_ms"]]
    histogram_chart(
        distribution_rows,
        title="队列等待时间分布",
        subtitle="等待时间 = 任务生成到首次派发的时间",
        out=chart_dir / "05_queue_wait_distribution.png",
    )

    ablation_rows = [r for r in summary if r["experiment"] == "ablation"]
    ablation_chart(
        ablation_rows,
        title="消融实验：不同机制的贡献",
        subtitle="网络条件：350ms 延迟、20% 丢包、10% 设备离线",
        out=chart_dir / "06_ablation_study.png",
    )

    timeline_rows = write_typical_timeline(out_dir, tasks)
    timeline_chart(
        timeline_rows,
        title="典型报警任务事件时间线",
        subtitle="来源：任务级 CSV 中一条成功的 night-door-anomaly 报警记录",
        out=chart_dir / "07_typical_event_timeline.png",
    )


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


def new_canvas(title: str, subtitle: str) -> tuple[Any, Any]:
    im = Image.new("RGB", (1600, 900), "#f5f7fb")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1600, 110], fill="#142033")
    d.rectangle([0, 110, 1600, 116], fill="#39a9bb")
    d.text((56, 28), title, font=font(34), fill="#ffffff")
    d.text((56, 134), subtitle, font=font(22), fill="#27344f")
    return im, d


def line_chart(
    points: list[tuple[float, float]],
    title: str,
    subtitle: str,
    x_label: str,
    y_label: str,
    out: Path,
    color: str,
    y_max: float | None = None,
) -> None:
    im, d = new_canvas(title, subtitle)
    left, top, right, bottom = 155, 230, 1470, 730
    draw_axes(d, left, top, right, bottom, x_label, y_label)
    if not points:
        im.save(out)
        return

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, x_max = min(xs), max(xs)
    y_min = 0.0
    y_max = y_max if y_max is not None else max(ys) * 1.15
    y_max = max(y_max, 1.0)

    prev = None
    for x, y in points:
        px = scale(x, x_min, x_max, left, right)
        py = scale(y, y_min, y_max, bottom, top)
        if prev:
            d.line([prev, (px, py)], fill=color, width=5)
        d.ellipse([px - 8, py - 8, px + 8, py + 8], fill=color)
        label_x = min(max(left + 8, px - 28), right - 70)
        label_y = max(top + 8, py - 38)
        d.text((label_x, label_y), f"{y:.1f}", font=font(18), fill="#1f2a44")
        prev = (px, py)

    for x in xs:
        px = scale(x, x_min, x_max, left, right)
        d.line([(px, bottom), (px, bottom + 8)], fill="#6b778d", width=2)
        label = f"{x:.0f}"
        d.text((px - 22, bottom + 18), label, font=font(18), fill="#47546a")
    for i in range(6):
        y = y_min + (y_max - y_min) * i / 5
        py = scale(y, y_min, y_max, bottom, top)
        d.line([(left - 8, py), (left, py)], fill="#6b778d", width=2)
        d.text((60, py - 12), f"{y:.0f}", font=font(18), fill="#47546a")
        if i:
            d.line([(left, py), (right, py)], fill="#e1e7f0", width=1)
    im.save(out)


def grouped_bar_chart(rows: list[dict[str, str]], title: str, subtitle: str, out: Path) -> None:
    im, d = new_canvas(title, subtitle)
    rows = sorted(rows, key=lambda r: MODE_ORDER.index(r["mode"]))
    labels = [r["mode_label"] for r in rows]
    success = [float(r["success_rate"]) * 100 for r in rows]
    alarm = [float(r["alarm_completion_rate"]) * 100 for r in rows]
    alarm_wait = [float(r.get("alarm_avg_queue_wait_ms", 0.0)) for r in rows]

    left, top, right, bottom = 150, 230, 1460, 520
    draw_axes(d, left, top, right, bottom, "", "百分比（%）")
    colors = ["#4f73d9", "#74bd6d"]
    group_w = (right - left) / max(len(rows), 1)
    bar_w = 70
    for i, label in enumerate(labels):
        cx = left + group_w * i + group_w / 2
        for j, value in enumerate([success[i], alarm[i]]):
            x1 = cx - bar_w - 10 + j * (bar_w + 20)
            x2 = x1 + bar_w
            y1 = scale(value, 0, 100, bottom, top)
            d.rounded_rectangle([x1, y1, x2, bottom], radius=8, fill=colors[j])
        label_y = max(top + 8, y1 - 28)
        d.text((x1 - 4, label_y), f"{value:.1f}", font=font(17), fill="#1f2a44")
        d.text((cx - 55, bottom + 22), label, font=font(19), fill="#47546a")
    draw_percent_ticks(d, left, top, bottom)
    legend(d, [(colors[0], "任务成功率"), (colors[1], "报警完成率")], 1260, 155)

    left2, top2, right2, bottom2 = 150, 650, 1460, 790
    d.text((150, 595), "报警任务平均排队等待时间（越低越好）", font=font(22), fill="#27344f")
    d.line([(left2, bottom2), (right2, bottom2)], fill="#6b778d", width=2)
    max_wait = max(alarm_wait + [1.0]) * 1.15
    for i, label in enumerate(labels):
        cx = left2 + group_w * i + group_w / 2
        value = alarm_wait[i]
        x1, x2 = cx - 82, cx + 82
        y1 = scale(value, 0, max_wait, bottom2, top2)
        d.rounded_rectangle([x1, y1, x2, bottom2], radius=8, fill="#ef9b3a")
        d.text((cx - 42, y1 - 30), f"{value:.0f}ms", font=font(18), fill="#1f2a44")
        d.text((cx - 55, bottom2 + 20), label, font=font(19), fill="#47546a")
    for i in range(4):
        value = max_wait * i / 3
        py = scale(value, 0, max_wait, bottom2, top2)
        d.text((70, py - 10), f"{value:.0f}", font=font(17), fill="#47546a")
        if i:
            d.line([(left2, py), (right2, py)], fill="#e1e7f0", width=1)
    im.save(out)


def simple_bar_chart(
    values: list[tuple[str, float]],
    title: str,
    subtitle: str,
    x_label: str,
    y_label: str,
    out: Path,
    y_max: float,
    color: str,
) -> None:
    im, d = new_canvas(title, subtitle)
    left, top, right, bottom = 150, 230, 1460, 725
    draw_axes(d, left, top, right, bottom, x_label, y_label)
    group_w = (right - left) / max(len(values), 1)
    for i, (label, value) in enumerate(values):
        cx = left + group_w * i + group_w / 2
        x1, x2 = cx - 70, cx + 70
        y1 = scale(value, 0, y_max, bottom, top)
        d.rounded_rectangle([x1, y1, x2, bottom], radius=10, fill=color)
        d.text((cx - 34, y1 - 32), f"{value:.1f}", font=font(20), fill="#1f2a44")
        d.text((cx - 58, bottom + 22), label, font=font(20), fill="#47546a")
    draw_percent_ticks(d, left, top, bottom)
    im.save(out)


def histogram_chart(rows: list[dict[str, str]], title: str, subtitle: str, out: Path) -> None:
    im, d = new_canvas(title, subtitle)
    left, top, right, bottom = 150, 230, 1460, 725
    draw_axes(d, left, top, right, bottom, "队列等待时间区间（ms）", "任务数量")
    bins = [0, 250, 500, 750, 1000, 1500, 2200, 3200]
    colors = {"fifo_rule": "#6d7f99", "priority": "#4f73d9", "fault_tolerant": "#74bd6d"}
    grouped: dict[str, list[int]] = {mode: [0] * (len(bins) - 1) for mode in colors}
    for row in rows:
        wait = float(row["queue_wait_ms"])
        mode = row["mode"]
        for idx in range(len(bins) - 1):
            if bins[idx] <= wait < bins[idx + 1]:
                grouped[mode][idx] += 1
                break
    max_count = max([max(v) for v in grouped.values()] + [1])
    bin_w = (right - left) / (len(bins) - 1)
    bar_w = 26
    for i in range(len(bins) - 1):
        cx = left + bin_w * i + bin_w / 2
        for j, mode in enumerate(MODE_ORDER):
            count = grouped[mode][i]
            x1 = cx - 45 + j * (bar_w + 8)
            x2 = x1 + bar_w
            y1 = scale(count, 0, max_count, bottom, top)
            d.rounded_rectangle([x1, y1, x2, bottom], radius=5, fill=colors[mode])
        d.text((cx - 48, bottom + 20), f"{bins[i]}-{bins[i + 1]}", font=font(15), fill="#47546a")
    for i in range(6):
        val = max_count * i / 5
        py = scale(val, 0, max_count, bottom, top)
        d.text((75, py - 11), f"{val:.0f}", font=font(17), fill="#47546a")
        if i:
            d.line([(left, py), (right, py)], fill="#e1e7f0", width=1)
    legend(d, [(colors[k], MODE_LABELS[k]) for k in MODE_ORDER], 990, 190)
    im.save(out)


def ablation_chart(rows: list[dict[str, str]], title: str, subtitle: str, out: Path) -> None:
    im, d = new_canvas(title, subtitle)
    rows = sorted(rows, key=lambda r: ABLATION_ORDER.index(r["mode"]))
    labels = [r["mode_label"] for r in rows]
    success = [float(r["success_rate"]) * 100 for r in rows]
    alarm = [float(r["alarm_completion_rate"]) * 100 for r in rows]
    response = [float(r["avg_response_ms"]) for r in rows]

    left, top, right, bottom = 120, 225, 1510, 520
    draw_axes(d, left, top, right, bottom, "", "百分比（%）")
    group_w = (right - left) / max(len(rows), 1)
    bar_w = 48
    colors = ["#4f73d9", "#74bd6d"]
    for i, label in enumerate(labels):
        cx = left + group_w * i + group_w / 2
        for j, value in enumerate([success[i], alarm[i]]):
            x1 = cx - bar_w - 8 + j * (bar_w + 16)
            x2 = x1 + bar_w
            y1 = scale(value, 0, 100, bottom, top)
            d.rounded_rectangle([x1, y1, x2, bottom], radius=7, fill=colors[j])
            d.text((x1 - 6, max(top + 6, y1 - 26)), f"{value:.1f}", font=font(15), fill="#1f2a44")
        d.text((cx - 68, bottom + 20), label, font=font(16), fill="#47546a")
    draw_percent_ticks(d, left, top, bottom)
    legend(d, [(colors[0], "任务成功率"), (colors[1], "报警完成率")], 1220, 155)

    left2, top2, right2, bottom2 = 120, 650, 1510, 790
    d.text((120, 590), "平均响应时间（越低越好）", font=font(22), fill="#27344f")
    d.line([(left2, bottom2), (right2, bottom2)], fill="#6b778d", width=2)
    max_response = max(response + [1.0]) * 1.15
    for i, label in enumerate(labels):
        cx = left2 + group_w * i + group_w / 2
        value = response[i]
        x1, x2 = cx - 58, cx + 58
        y1 = scale(value, 0, max_response, bottom2, top2)
        d.rounded_rectangle([x1, y1, x2, bottom2], radius=8, fill="#ef9b3a")
        d.text((cx - 46, max(top2 + 4, y1 - 28)), f"{value:.0f}", font=font(16), fill="#1f2a44")
        d.text((cx - 68, bottom2 + 20), label, font=font(16), fill="#47546a")
    for i in range(4):
        value = max_response * i / 3
        py = scale(value, 0, max_response, bottom2, top2)
        d.text((50, py - 10), f"{value:.0f}", font=font(16), fill="#47546a")
        if i:
            d.line([(left2, py), (right2, py)], fill="#e1e7f0", width=1)
    im.save(out)


def write_typical_timeline(out_dir: Path, tasks: list[dict[str, str]]) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in tasks
        if row["device"] == "alarm"
        and row["command"] == "on"
        and row["reason"] == "night-door-anomaly"
        and row["status"] == "success"
        and row["first_dispatch_at"]
        and row["completed_at"]
    ]
    candidates.sort(
        key=lambda r: (
            r["mode"] != "fault_tolerant",
            r["experiment"] != "ablation",
            int(r.get("attempts") or 0) < 2,
            float(r["response_ms"] or 0),
        )
    )
    if not candidates:
        write_csv(out_dir / "typical_timeline.csv", [])
        return []

    task = candidates[0]
    created = float(task["created_at"])
    dispatched = float(task["first_dispatch_at"])
    completed = float(task["completed_at"])
    rows: list[dict[str, Any]] = [
        {
            "event": "触发并入队",
            "at_s": round(created, 4),
            "delta_ms": 0.0,
            "detail": f"door=open, pir=false, p={task['priority']}",
        },
        {
            "event": "首次派发命令",
            "at_s": round(dispatched, 4),
            "delta_ms": round((dispatched - created) * 1000.0, 2),
            "detail": f"queue_wait={task['queue_wait_ms']}ms",
        },
    ]
    attempts = int(task["attempts"])
    if attempts > 1:
        retry_at = dispatched + (completed - dispatched) / attempts
        rows.append(
            {
                "event": "超时重试",
                "at_s": round(retry_at, 4),
                "delta_ms": round((retry_at - created) * 1000.0, 2),
                "detail": f"attempts={attempts}",
            }
        )
    rows.append(
        {
            "event": "设备 ACK 确认",
            "at_s": round(completed, 4),
            "delta_ms": round((completed - created) * 1000.0, 2),
            "detail": f"response={task['response_ms']}ms",
        }
    )
    write_csv(out_dir / "typical_timeline.csv", rows)
    return rows


def timeline_chart(rows: list[dict[str, Any]], title: str, subtitle: str, out: Path) -> None:
    im, d = new_canvas(title, subtitle)
    if not rows:
        d.text((100, 330), "未找到可用于绘制时间线的成功报警任务。", font=font(28), fill="#27344f")
        im.save(out)
        return

    left, right = 220, 1410
    y = 455
    max_delta = max(float(row["delta_ms"]) for row in rows) or 1.0
    d.line([(left, y), (right, y)], fill="#6b778d", width=4)
    for idx, row in enumerate(rows):
        x = scale(float(row["delta_ms"]), 0, max_delta, left, right)
        color = ["#4f73d9", "#39a9bb", "#ef9b3a", "#d95f59", "#74bd6d", "#5b6b84"][idx % 6]
        d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=color)
        label_y = y - 150 if idx % 2 == 0 else y + 55
        d.line([(x, y), (x, label_y + 36)], fill=color, width=3)
        d.rounded_rectangle([x - 135, label_y, x + 135, label_y + 94], radius=14, fill="#ffffff", outline="#d3dce9", width=2)
        d.text((x - 112, label_y + 16), str(row["event"]), font=font(20), fill="#27344f")
        d.text((x - 112, label_y + 50), f"+{float(row['delta_ms']):.0f} ms", font=font(18), fill=color)
        if row.get("detail"):
            detail = str(row["detail"])
            d.text((x - 112, label_y + 72), detail[:28], font=font(14), fill="#637189")

    d.text((88, 760), "说明：时间线来自任务级 CSV，展示从规则触发到设备 ACK 的完整闭环。", font=font(22), fill="#27344f")
    im.save(out)


def draw_axes(d: Any, left: int, top: int, right: int, bottom: int, x_label: str, y_label: str) -> None:
    d.line([(left, bottom), (right, bottom)], fill="#6b778d", width=2)
    d.line([(left, top), (left, bottom)], fill="#6b778d", width=2)
    if x_label:
        d.text(((left + right) // 2 - 100, 800), x_label, font=font(20), fill="#27344f")
    if y_label:
        d.text((35, top - 45), y_label, font=font(20), fill="#27344f")


def draw_percent_ticks(d: Any, left: int, top: int, bottom: int) -> None:
    for i in range(6):
        y = i * 20
        py = scale(y, 0, 100, bottom, top)
        d.line([(left - 8, py), (left, py)], fill="#6b778d", width=2)
        d.text((72, py - 12), f"{y}", font=font(18), fill="#47546a")
        if i:
            d.line([(left, py), (1460, py)], fill="#e1e7f0", width=1)


def legend(d: Any, items: list[tuple[str, str]], x: int, y: int) -> None:
    for i, (color, label) in enumerate(items):
        yy = y + i * 34
        d.rounded_rectangle([x, yy, x + 24, yy + 18], radius=4, fill=color)
        d.text((x + 34, yy - 4), label, font=font(18), fill="#27344f")


def scale(v: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    if in_max == in_min:
        return (out_min + out_max) / 2
    return out_min + (v - in_min) * (out_max - out_min) / (in_max - in_min)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run edge-agent reliability experiments.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory for CSV and charts.")
    parser.add_argument("--horizon", type=int, default=220, help="Virtual seconds per run.")
    parser.add_argument("--reps", type=int, default=6, help="Base repetitions per condition.")
    parser.add_argument("--plot-only", action="store_true", help="Only regenerate charts from existing CSV files.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.plot_only:
        generate_charts(args.out)
    else:
        run_suite(args.out, horizon_s=args.horizon, reps=args.reps)
    print(f"Experiment results written to: {args.out}")


if __name__ == "__main__":
    main()

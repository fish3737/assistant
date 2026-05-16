"""Start all local modules for quick demo."""

from __future__ import annotations

import signal
import subprocess
import sys
import time


def main() -> None:
    commands = [
        ("device", [sys.executable, "-u", "-m", "src.device.device_executor"]),
        ("agent", [sys.executable, "-u", "-m", "src.agent.edge_agent"]),
        ("sensor", [sys.executable, "-u", "-m", "src.simulator.sensor_simulator"]),
    ]

    processes: list[subprocess.Popen[bytes]] = []
    for name, cmd in commands:
        proc = subprocess.Popen(cmd)
        processes.append(proc)
        print(f"[run_demo] started {name} pid={proc.pid}")

    print("[run_demo] Press Ctrl+C to stop all modules.")
    try:
        while True:
            time.sleep(1)
            for proc in processes:
                if proc.poll() is not None:
                    raise RuntimeError(f"Subprocess exited unexpectedly: pid={proc.pid}")
    except KeyboardInterrupt:
        print("\n[run_demo] stopping...")
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()

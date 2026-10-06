"""GPU thermal guard for evaluation runs.

The development laptop's GPU climbs ~2C/s under model inference and the owner
set a hard 93C ceiling, so a long evaluation must never run unattended without
a brake: wait for a cool start, and trip a watchdog well below the ceiling
(polling can overshoot by 2-3C). Tripping stops generation on the server by
restarting the model container - killing only this Python process would leave
the GPU grinding on the in-flight request - then exits.

No-ops (returns None) when nvidia-smi is absent, e.g. a CPU-only or remote host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time


def gpu_temp() -> int | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        return max(int(x) for x in out.split())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def wait_until_cool(start_below: int = 70, max_wait_s: int = 900) -> bool:
    """Block until the GPU is at or below `start_below`. False if it never cools
    (a hot baseline, e.g. an overlay holding the GPU busy) - the caller should stop
    and say so rather than run hot."""
    deadline = time.monotonic() + max_wait_s
    while True:
        temp = gpu_temp()
        if temp is None or temp <= start_below:
            return True
        if time.monotonic() > deadline:
            return False
        print(f"  GPU {temp}C > {start_below}C, cooling...", flush=True)
        time.sleep(5)


def start_watchdog(trip_at: int = 88, container: str | None = None, poll_s: float = 0.25,
                   stop_cmd: list[str] | None = None, log_path: str | None = None) -> None:
    if gpu_temp() is None:
        return

    def watch() -> None:
        while True:
            temp = gpu_temp()
            if temp is not None and temp >= trip_at:
                print(f"\n!! GPU {temp}C >= {trip_at}C - stopping the model and exiting", flush=True)
                # stop *generation on the server*: exiting this process would leave the GPU
                # grinding on the in-flight request. Ollama in Docker: restart its container;
                # LM Studio: unload the model (stop_cmd, e.g. ["lms", "unload", "--all"]).
                if stop_cmd:
                    subprocess.run(stop_cmd, capture_output=True, timeout=60)
                if container:
                    subprocess.run(["docker", "restart", container], capture_output=True, timeout=60)
                os._exit(3)
            if log_path and temp is not None:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%H:%M:%S')} {temp}\n")
            time.sleep(poll_s)

    threading.Thread(target=watch, daemon=True).start()

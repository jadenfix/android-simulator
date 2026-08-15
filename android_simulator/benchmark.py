from __future__ import annotations

import statistics
import time
from typing import Any

from .computer_use import DeviceController


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
    p50 = ordered[(len(ordered) - 1) // 2]
    p95 = ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))]
    return {
        "mean_ms": round(statistics.fmean(ordered), 3),
        "p50_ms": round(p50, 3),
        "p95_ms": round(p95, 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
    }


def run_benchmark(
    controller: DeviceController,
    *,
    iterations: int = 20,
    batch_size: int = 8,
    warmup: int = 2,
) -> dict[str, Any]:
    iterations = max(3, min(iterations, 200))
    batch_size = max(2, min(batch_size, 12))
    warmup = max(0, min(warmup, 10))

    for _ in range(warmup):
        controller.observe()
        controller.act({"type": "wait", "seconds": 0})

    observations: list[float] = []
    singles: list[float] = []
    batches: list[float] = []

    for _ in range(iterations):
        started = time.perf_counter()
        controller.observe()
        observations.append((time.perf_counter() - started) * 1000)

    # Harmless zero-second waits isolate ADB transaction overhead without changing device state.
    for _ in range(iterations):
        started = time.perf_counter()
        for _ in range(batch_size):
            controller.act({"type": "wait", "seconds": 0})
        singles.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        controller.macro([{"type": "wait", "seconds": 0} for _ in range(batch_size)])
        batches.append((time.perf_counter() - started) * 1000)

    single_mean = statistics.fmean(singles)
    batch_mean = statistics.fmean(batches)
    speedup = single_mean / batch_mean if batch_mean > 0 else 0.0
    return {
        "iterations": iterations,
        "batch_size": batch_size,
        "observation": _stats(observations),
        "sequential_actions": _stats(singles),
        "single_transaction_batch": _stats(batches),
        "effective_batch_speedup_x": round(speedup, 3),
        "note": "action benchmark uses zero-second waits to isolate host/ADB transaction overhead",
    }

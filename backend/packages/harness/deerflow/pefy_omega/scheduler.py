"""Dependency-aware parallel execution planning for MƐTAFLOW Ω."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .policy import Mode


@dataclass(frozen=True, slots=True)
class TaskNode:
    task_id: str
    objective: str
    depends_on: tuple[str, ...] = ()
    priority: int = 50
    risk: str = "normal"


@dataclass(frozen=True, slots=True)
class ExecutionWave:
    wave: int
    tasks: tuple[TaskNode, ...]


_MODE_PARALLELISM: dict[Mode, int] = {
    Mode.FLASH: 1,
    Mode.STANDARD: 4,
    Mode.PRO: 8,
    Mode.ULTRA: 12,
    Mode.SOVEREIGN: 4,
    Mode.WARROOM: 3,
}


def recommended_parallelism(mode: Mode, requested_max: int | None = None) -> int:
    """Return a risk-aware concurrency ceiling for the selected mode."""

    default = _MODE_PARALLELISM[mode]
    if requested_max is None:
        return default
    if requested_max < 1:
        raise ValueError("requested_max must be >= 1")
    return min(default, requested_max)


def build_execution_waves(
    tasks: Iterable[TaskNode],
    *,
    mode: Mode = Mode.STANDARD,
    requested_max_parallel: int | None = None,
) -> tuple[ExecutionWave, ...]:
    """Topologically group independent tasks into bounded parallel waves.

    Independent tasks execute concurrently up to the mode-specific ceiling.
    Dependencies always override speed. Unknown dependencies and cycles fail
    closed instead of silently producing an invalid plan.
    """

    task_list = list(tasks)
    by_id = {task.task_id: task for task in task_list}
    if len(by_id) != len(task_list):
        raise ValueError("task_id values must be unique")

    for task in task_list:
        unknown = [dep for dep in task.depends_on if dep not in by_id]
        if unknown:
            raise ValueError(f"task {task.task_id!r} has unknown dependencies: {unknown}")
        if task.task_id in task.depends_on:
            raise ValueError(f"task {task.task_id!r} cannot depend on itself")

    max_parallel = recommended_parallelism(mode, requested_max_parallel)
    remaining = set(by_id)
    completed: set[str] = set()
    waves: list[ExecutionWave] = []
    wave_index = 0

    while remaining:
        ready = [
            by_id[task_id]
            for task_id in remaining
            if set(by_id[task_id].depends_on).issubset(completed)
        ]
        if not ready:
            cycle_nodes = sorted(remaining)
            raise ValueError(f"task dependency cycle detected among: {cycle_nodes}")

        # Higher priority first, then deterministic task ID ordering.
        ready.sort(key=lambda task: (-task.priority, task.task_id))

        # A readiness set may exceed the safe concurrency limit. Split it into
        # multiple waves while retaining dependency correctness.
        batch = ready[:max_parallel]
        wave_index += 1
        waves.append(ExecutionWave(wave=wave_index, tasks=tuple(batch)))

        for task in batch:
            remaining.remove(task.task_id)
            completed.add(task.task_id)

    return tuple(waves)


def burst_smoothing_offsets(
    task_count: int,
    *,
    mode: Mode = Mode.STANDARD,
    base_interval_ms: int = 75,
) -> tuple[int, ...]:
    """Return small launch offsets to reduce synchronized provider bursts.

    The offsets are scheduling hints in milliseconds, not sleeps. Runtime
    adapters may apply them when many independent model/tool calls start at
    once. More sensitive modes use wider spacing by default.
    """

    if task_count < 0:
        raise ValueError("task_count must be >= 0")
    if base_interval_ms < 0:
        raise ValueError("base_interval_ms must be >= 0")

    multiplier = {
        Mode.FLASH: 0,
        Mode.STANDARD: 1,
        Mode.PRO: 1,
        Mode.ULTRA: 1,
        Mode.SOVEREIGN: 2,
        Mode.WARROOM: 2,
    }[mode]
    interval = base_interval_ms * multiplier
    return tuple(index * interval for index in range(task_count))

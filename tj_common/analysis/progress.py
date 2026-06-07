"""Batch progress reporting for long-running victim analysis."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

EmitFn = Callable[[str], None]


@dataclass
class AnalysisProgress:
    """Options for batch processing with periodic status and optional parallel agents."""

    label: str = "Анализ"
    batch_size: int = 50
    status_interval_sec: float = 10.0
    min_items: int = 10
    agent_chunk_size: int = 0
    emit: EmitFn | None = None


class ThreadSafeProgressTracker:
    """Wrap ProgressTracker for concurrent agent workers."""

    def __init__(self, tracker: ProgressTracker) -> None:
        import threading

        self._tracker = tracker
        self._lock = threading.Lock()

    def tick(self, *, error: bool = False) -> None:
        with self._lock:
            self._tracker.tick(error=error)

    def finish(self) -> None:
        with self._lock:
            self._tracker.finish()


class ProgressTracker:
    def __init__(
        self,
        total: int,
        *,
        label: str,
        status_interval_sec: float = 10.0,
        emit: EmitFn | None = None,
    ) -> None:
        self.total = total
        self.label = label
        self.status_interval_sec = status_interval_sec
        self.emit = emit or (lambda msg: print(msg, flush=True))
        self.done = 0
        self.errors = 0
        self._last_status = time.monotonic()
        self._emit_status(force=True)

    def tick(self, *, error: bool = False) -> None:
        self.done += 1
        if error:
            self.errors += 1
        now = time.monotonic()
        if now - self._last_status >= self.status_interval_sec or self.done >= self.total:
            self._emit_status()
            self._last_status = now

    def finish(self) -> None:
        self._emit_status(force=True)

    def _emit_status(self, *, force: bool = False) -> None:
        remaining = max(self.total - self.done, 0)
        msg = (
            f"[{self.label}] обработано {self.done} / {self.total}, "
            f"осталось {remaining}"
        )
        if self.errors:
            msg += f", ошибок {self.errors}"
        self.emit(msg)


def iter_batches(items: list[T], batch_size: int) -> Iterator[list[T]]:
    size = max(1, batch_size)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def should_report_progress(total: int, progress: AnalysisProgress | None) -> bool:
    return progress is not None and total >= progress.min_items


def should_use_parallel_agents(
    total: int, progress: AnalysisProgress | None
) -> bool:
    return (
        progress is not None
        and progress.agent_chunk_size > 0
        and total > progress.agent_chunk_size
    )

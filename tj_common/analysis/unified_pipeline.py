"""Run TLOCK, TTIMEOUT, and TDEADLOCK analysis in one pass."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from tj_common.analysis.deadlock_pipeline import run_deadlock_analysis
from tj_common.analysis.pipeline import run_analysis
from tj_common.analysis.progress import AnalysisProgress
from tj_common.models import AnalysisResult
from tj_common.models_deadlock import DeadlockAnalysisResult, DeadlockQueryFilters
from tj_common.models import QueryFilters
from tj_common.sources.deadlock_base import DeadlockDataSource
from tj_common.sources.base import LogSource


class AnalyzerKind(str, Enum):
    tlock = "tlock"
    ttimeout = "ttimeout"
    tdeadlock = "tdeadlock"


ALL_ANALYZERS = (AnalyzerKind.tlock, AnalyzerKind.ttimeout, AnalyzerKind.tdeadlock)


@dataclass
class UnifiedAnalysisResult:
    tlock: AnalysisResult | None = None
    ttimeout: AnalysisResult | None = None
    tdeadlock: DeadlockAnalysisResult | None = None
    skipped: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "tlock_victims": len(self.tlock.victims) if self.tlock else 0,
            "ttimeout_victims": len(self.ttimeout.victims) if self.ttimeout else 0,
            "tdeadlock_cases": len(self.tdeadlock.cases) if self.tdeadlock else 0,
            "total_errors": sum(
                len(r.errors)
                for r in (
                    self.tlock,
                    self.ttimeout,
                    self.tdeadlock,
                )
                if r is not None
            ),
        }


def run_unified_analysis(
    *,
    kinds: list[AnalyzerKind],
    tlock_source: LogSource | None = None,
    ttimeout_source: LogSource | None = None,
    tdeadlock_source: DeadlockDataSource | None = None,
    tlock_filters: QueryFilters | None = None,
    ttimeout_filters: QueryFilters | None = None,
    tdeadlock_filters: DeadlockQueryFilters | None = None,
    config_catalog: str | None = None,
    progress: AnalysisProgress | None = None,
) -> UnifiedAnalysisResult:
    result = UnifiedAnalysisResult()

    if AnalyzerKind.tlock in kinds:
        if tlock_source is None or tlock_filters is None:
            result.skipped.append("tlock: missing source or filters")
        else:
            tlock_progress = _child_progress(progress, "TLOCK")
            result.tlock = run_analysis(
                tlock_source, tlock_filters, progress=tlock_progress
            )
    else:
        result.skipped.append("tlock")

    if AnalyzerKind.ttimeout in kinds:
        if ttimeout_source is None or ttimeout_filters is None:
            result.skipped.append("ttimeout: missing source or filters")
        else:
            ttimeout_progress = _child_progress(progress, "TTIMEOUT")
            result.ttimeout = run_analysis(
                ttimeout_source, ttimeout_filters, progress=ttimeout_progress
            )
    else:
        result.skipped.append("ttimeout")

    if AnalyzerKind.tdeadlock in kinds:
        if tdeadlock_source is None or tdeadlock_filters is None:
            result.skipped.append("tdeadlock: missing source or filters")
        else:
            tdeadlock_progress = _child_progress(progress, "TDEADLOCK")
            result.tdeadlock = run_deadlock_analysis(
                tdeadlock_source,
                tdeadlock_filters,
                config_catalog=config_catalog,
                progress=tdeadlock_progress,
            )
    else:
        result.skipped.append("tdeadlock")

    return result


def _child_progress(
    parent: AnalysisProgress | None, label: str
) -> AnalysisProgress | None:
    if parent is None:
        return None
    return AnalysisProgress(
        label=label,
        batch_size=parent.batch_size,
        status_interval_sec=parent.status_interval_sec,
        min_items=parent.min_items,
        agent_chunk_size=parent.agent_chunk_size,
        emit=parent.emit,
    )

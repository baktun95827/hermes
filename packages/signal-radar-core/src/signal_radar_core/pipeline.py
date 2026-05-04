from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .analysis_input import build_analysis_input as build_analysis_input_core
from .memory_application import apply_memory_update


@dataclass(frozen=True)
class PipelineResult:
    exit_code: int
    stdout: str
    stderr: str


class PipelineError(RuntimeError):
    def __init__(self, message: str, result: PipelineResult):
        super().__init__(message)
        self.result = result


def pipeline_error(action: str, exc: Exception) -> PipelineError:
    result = PipelineResult(
        exit_code=1,
        stdout="",
        stderr=f"{type(exc).__name__}: {exc}\n",
    )
    return PipelineError(f"{action} failed: {exc}", result)


def build_analysis_input(
    *,
    config_path: str,
    collector_batch_path: str | Path | None = None,
    skill_dir: str | Path | None = None,
) -> PipelineResult:
    del skill_dir
    try:
        result = build_analysis_input_core(
            config_path=config_path,
            collector_batch_path=collector_batch_path,
        )
        return PipelineResult(exit_code=0, stdout=result.to_stdout(), stderr="")
    except Exception as exc:
        raise pipeline_error("build-analysis-input", exc) from exc


def apply_memory(
    *,
    config_path: str,
    summary_path: str | Path,
    skill_dir: str | Path | None = None,
) -> PipelineResult:
    del skill_dir
    try:
        result = apply_memory_update(
            config_path=config_path,
            summary_path=summary_path,
        )
        return PipelineResult(exit_code=0, stdout=result.to_stdout(), stderr="")
    except Exception as exc:
        raise pipeline_error("apply-memory", exc) from exc

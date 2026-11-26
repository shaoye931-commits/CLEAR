from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


TaskId = int | str


@dataclass(frozen=True)
class FunctionMetadata:
    name: str
    signature: str
    positional_parameters: tuple[str, ...]


@dataclass(frozen=True)
class TestCase:
    ordinal: int
    source: str
    setup_code: str = ""

    def script(self) -> str:
        parts = [part for part in (self.setup_code, self.source) if part]
        return "\n\n".join(parts) + "\n"


@dataclass(frozen=True)
class GenerationTask:
    """Task specifications plus the two public tests used after generation."""

    dataset: str
    task_id: TaskId
    base_problem: str | None
    extended_problem: str
    base_functions: tuple[FunctionMetadata, ...]
    extended_functions: tuple[FunctionMetadata, ...]
    public_tests: tuple[TestCase, ...]


@dataclass(frozen=True)
class EvaluationTask:
    """Held-out data intended only for the future final evaluator."""

    dataset: str
    task_id: TaskId
    held_out_tests: tuple[TestCase, ...]


@dataclass(frozen=True)
class DatasetReport:
    dataset: str
    source_path: Path
    original_count: int
    valid_count: int
    filtered_reasons: Mapping[str, int]
    issues: Mapping[str, int]
    total_tests: int
    public_tests: int
    held_out_tests: int


@dataclass(frozen=True)
class GenerationDataset:
    report: DatasetReport
    tasks: tuple[GenerationTask, ...]


@dataclass(frozen=True)
class EvaluationDataset:
    report: DatasetReport
    tasks: tuple[EvaluationTask, ...]

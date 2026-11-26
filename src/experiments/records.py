from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.models import TaskId


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class CandidateSnapshot:
    stage: str
    code: str | None
    content_hash: str | None

    @classmethod
    def capture(cls, stage: str, code: str | None) -> "CandidateSnapshot":
        return cls(stage, code, code_hash(code) if code is not None else None)


@dataclass(frozen=True)
class SealedCandidate:
    dataset: str
    task_id: TaskId
    code: str
    content_hash: str
    seal_reason: str
    public_test_status: str
    refinement_iterations: int
    state: str = "SEALED"

    @classmethod
    def create(
        cls,
        dataset: str,
        task_id: TaskId,
        code: str,
        seal_reason: str,
        public_test_status: str,
        refinement_iterations: int,
    ) -> "SealedCandidate":
        return cls(
            dataset,
            task_id,
            code,
            code_hash(code),
            seal_reason,
            public_test_status,
            refinement_iterations,
        )


@dataclass
class UsageTotals:
    call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    usage_unavailable_calls: int = 0
    estimated_cost: float = 0.0
    cost_unavailable_calls: int = 0
    request_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(
        self,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        elapsed_seconds: float,
        *,
        calls: int = 1,
        reasoning_tokens: int | None = None,
        estimated_cost: float | None = None,
    ) -> None:
        self.call_count += calls
        self.request_seconds += elapsed_seconds
        if estimated_cost is None:
            self.cost_unavailable_calls += calls
        else:
            self.estimated_cost += estimated_cost
        if prompt_tokens is None or completion_tokens is None:
            self.usage_unavailable_calls += calls
            return
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        if reasoning_tokens is not None:
            self.reasoning_tokens += reasoning_tokens


@dataclass
class IterationRecord:
    iteration: int
    static_check: Any
    trace: Any = None
    diagnosis: Any = None
    constraints: Any = None
    action: str | None = None
    generation: Any = None


@dataclass
class TaskRunRecord:
    task_id: TaskId
    dataset: str
    model: str
    run_id: str
    config: dict[str, Any]
    contract_result: Any = None
    initial_generation: Any = None
    iterations: list[IterationRecord] = field(default_factory=list)
    snapshots: list[CandidateSnapshot] = field(default_factory=list)
    sealed_candidate: SealedCandidate | None = None
    evaluation: Any = None
    usage: UsageTotals = field(default_factory=UsageTotals)
    total_seconds: float = 0.0
    terminal_status: str = "running"
    failure_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return to_jsonable(self)

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable

from src.experiments.records import SealedCandidate
from src.models import EvaluationTask, TaskId
from src.reuse import DockerUnavailableError, SandboxResult, run_untrusted_python


class EvaluationStatus(str, Enum):
    PASS = "pass"
    TEST_FAILED = "test_failed"
    EXECUTION_ERROR = "execution_error"
    TIMEOUT = "timeout"
    ENVIRONMENT_ERROR = "environment_error"
    NO_HELD_OUT_TESTS = "no_held_out_tests"
    NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True)
class EvaluationResult:
    task_id: TaskId
    status: EvaluationStatus
    passed: bool
    held_out_test_count: int
    passed_test_count: int
    exit_code: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    execution_kind: str


@dataclass(frozen=True)
class PassAtOneSummary:
    total_tasks: int
    successful_tasks: int
    pass_at_1_percent: float


def evaluate_sealed_candidate(
    candidate: SealedCandidate,
    task: EvaluationTask,
    *,
    executor: Callable[..., SandboxResult] = run_untrusted_python,
    image: str = "clear-sandbox:latest",
    time_limit_s: int = 3,
) -> EvaluationResult:
    execution_kind = "docker" if executor is run_untrusted_python else "mock"
    if candidate.state != "SEALED":
        raise ValueError("only sealed candidates may be evaluated")
    if candidate.dataset != task.dataset or candidate.task_id != task.task_id:
        raise ValueError("sealed candidate and evaluation task do not match")
    if not task.held_out_tests:
        return EvaluationResult(
            task.task_id, EvaluationStatus.NO_HELD_OUT_TESTS, False, 0, 0, None, "", "", 0.0,
            "none",
        )
    started = time.perf_counter()
    passed_count = 0
    status = EvaluationStatus.PASS
    exit_code = 0
    stdout: list[str] = []
    stderr: list[str] = []
    priority = {
        EvaluationStatus.PASS: 0,
        EvaluationStatus.TEST_FAILED: 1,
        EvaluationStatus.EXECUTION_ERROR: 2,
        EvaluationStatus.TIMEOUT: 3,
    }
    for test in task.held_out_tests:
        try:
            execution = executor(
                candidate.code,
                "from solution import *\n" + test.script(),
                image=image,
                time_limit_s=time_limit_s,
            )
        except DockerUnavailableError as error:
            return EvaluationResult(
                task.task_id, EvaluationStatus.ENVIRONMENT_ERROR, False,
                len(task.held_out_tests), passed_count, None, "\n".join(stdout), str(error),
                time.perf_counter() - started, execution_kind,
            )
        except Exception as error:
            current = EvaluationStatus.EXECUTION_ERROR
            execution = None
            stderr.append(f"test {test.ordinal}: {type(error).__name__}: {error}")
        else:
            stdout.append(execution.stdout)
            stderr.append(execution.stderr)
            if execution.success:
                passed_count += 1
                continue
            if execution.exit_code == 124:
                current = EvaluationStatus.TIMEOUT
            elif "AssertionError" in execution.stdout + execution.stderr:
                current = EvaluationStatus.TEST_FAILED
            else:
                current = EvaluationStatus.EXECUTION_ERROR
        if priority[current] > priority[status]:
            status = current
            exit_code = execution.exit_code if execution else None
    return EvaluationResult(
        task.task_id,
        status,
        status is EvaluationStatus.PASS,
        len(task.held_out_tests),
        passed_count,
        exit_code,
        "\n".join(stdout),
        "\n".join(stderr),
        time.perf_counter() - started,
        execution_kind,
    )


def calculate_pass_at_1(results: Iterable[EvaluationResult]) -> PassAtOneSummary:
    items = tuple(results)
    successful = sum(result.passed for result in items)
    percentage = successful / len(items) * 100 if items else 0.0
    return PassAtOneSummary(len(items), successful, percentage)


def missing_candidate_result(task: EvaluationTask) -> EvaluationResult:
    """Keep a generation failure in the formal evaluation denominator."""
    return EvaluationResult(
        task.task_id,
        EvaluationStatus.NO_CANDIDATE,
        False,
        len(task.held_out_tests),
        0,
        None,
        "",
        "no sealed candidate was produced",
        0.0,
        "none",
    )

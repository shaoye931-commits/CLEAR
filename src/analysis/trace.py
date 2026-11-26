from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from string import Template

from src.analysis.contract import DependencyContract
from src.models import GenerationTask, TestCase
from src.reuse import run_untrusted_python_with_artifact


class TestExecutionStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


@dataclass(frozen=True)
class PublicTestOutcome:
    ordinal: int
    status: str
    error_type: str | None
    error_summary: str | None


@dataclass(frozen=True)
class FunctionCallRecord:
    call_id: int
    function_name: str
    args_summary: str
    kwargs_summary: str
    status: str
    output_summary: str | None
    error_type: str | None
    error_summary: str | None


@dataclass(frozen=True)
class TraceResult:
    execution_status: TestExecutionStatus
    test_outcomes: tuple[PublicTestOutcome, ...]
    calls: tuple[FunctionCallRecord, ...]
    sandbox_stdout: str = ""
    sandbox_stderr: str = ""


_DRIVER = Template(
    r'''
import base64
import functools
import json
import os

_artifact_name = $ARTIFACT
_base_name = $BASE_NAME
_test_source = base64.b64decode($TEST_SOURCE).decode("utf-8")
_calls = []
_next_call_id = 0
_execution_status = "ok"
_error_type = None
_error_summary = None
_original = None
_hard_exit = os._exit
_trusted_open = open
_trusted_json_dump = json.dump

def _summary(value):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except BaseException:
        try:
            text = repr(value)
        except BaseException:
            text = "<unrepresentable>"
    return text if len(text) <= 512 else text[:509] + "..."

try:
    import solution
    _original = getattr(solution, _base_name)

    @functools.wraps(_original)
    def _proxy(*args, **kwargs):
        global _next_call_id
        _next_call_id += 1
        call_id = _next_call_id
        args_summary = _summary(args)
        kwargs_summary = _summary(kwargs)
        try:
            result = _original(*args, **kwargs)
        except BaseException as error:
            _calls.append({
                "call_id": call_id,
                "function_name": _base_name,
                "args_summary": args_summary,
                "kwargs_summary": kwargs_summary,
                "status": "fail",
                "output_summary": None,
                "error_type": type(error).__name__,
                "error_summary": _summary(str(error)),
            })
            raise
        _calls.append({
            "call_id": call_id,
            "function_name": _base_name,
            "args_summary": args_summary,
            "kwargs_summary": kwargs_summary,
            "status": "ok",
            "output_summary": _summary(result),
            "error_type": None,
            "error_summary": None,
        })
        return result

    setattr(solution, _base_name, _proxy)
    namespace = {name: value for name, value in vars(solution).items() if not name.startswith("__")}
    try:
        exec(compile(_test_source, "<public_test>", "exec"), namespace, namespace)
    except BaseException as error:
        _execution_status = "fail"
        _error_type = type(error).__name__
        _error_summary = _summary(str(error))
except BaseException as error:
    _execution_status = "fail"
    _error_type = type(error).__name__
    _error_summary = _summary(str(error))
finally:
    if _original is not None:
        try:
            setattr(solution, _base_name, _original)
        except BaseException:
            pass
    payload = {
        "version": 1,
        "execution_status": _execution_status,
        "error_type": _error_type,
        "error_summary": _error_summary,
        "calls": _calls,
    }
    try:
        with _trusted_open(_artifact_name, "x", encoding="utf-8") as handle:
            _trusted_json_dump(payload, handle, ensure_ascii=False, sort_keys=True)
    except BaseException:
        _hard_exit(2)
    _hard_exit(0 if _execution_status == "ok" else 1)
'''
)


def _collect_one(
    test: TestCase,
    contract: DependencyContract,
    candidate_code: str,
    *,
    image: str,
    time_limit_s: int,
) -> tuple[PublicTestOutcome, tuple[FunctionCallRecord, ...], str, str] | None:
    artifact_name = f".clear_trace_{uuid.uuid4().hex}.json"
    test_source = base64.b64encode(test.script().encode("utf-8")).decode("ascii")
    driver = _DRIVER.substitute(
        ARTIFACT=repr(artifact_name),
        BASE_NAME=repr(contract.base_name),
        TEST_SOURCE=repr(test_source),
    )
    run = run_untrusted_python_with_artifact(
        candidate_code,
        driver,
        artifact_name=artifact_name,
        image=image,
        time_limit_s=time_limit_s,
    )
    if run.execution.exit_code == 124 and run.artifact is None:
        outcome = PublicTestOutcome(
            test.ordinal,
            "fail",
            "TimeoutError",
            f"public test exceeded {time_limit_s} seconds",
        )
        return outcome, (), run.execution.stdout, run.execution.stderr
    if run.execution.exit_code not in (0, 1) or run.artifact is None:
        return None
    try:
        payload = json.loads(run.artifact)
        if payload.get("version") != 1:
            return None
        calls = tuple(FunctionCallRecord(**item) for item in payload["calls"])
        status = str(payload["execution_status"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    outcome = PublicTestOutcome(
        test.ordinal,
        status,
        payload.get("error_type"),
        payload.get("error_summary"),
    )
    return outcome, calls, run.execution.stdout, run.execution.stderr


def collect_public_trace(
    task: GenerationTask,
    contract: DependencyContract,
    candidate_code: str,
    *,
    image: str = "clear-sandbox:latest",
    time_limit_s: int = 3,
) -> TraceResult:
    outcomes: list[PublicTestOutcome] = []
    calls: list[FunctionCallRecord] = []
    stdout: list[str] = []
    stderr: list[str] = []
    call_offset = 0
    for test in task.public_tests:
        captured = _collect_one(
            test,
            contract,
            candidate_code,
            image=image,
            time_limit_s=time_limit_s,
        )
        if captured is None:
            return TraceResult(
                TestExecutionStatus.INFRASTRUCTURE_ERROR,
                tuple(outcomes),
                tuple(calls),
                "\n".join(stdout),
                "\n".join(stderr),
            )
        outcome, test_calls, test_stdout, test_stderr = captured
        outcomes.append(outcome)
        calls.extend(replace(call, call_id=call.call_id + call_offset) for call in test_calls)
        call_offset += max((call.call_id for call in test_calls), default=0)
        stdout.append(test_stdout)
        stderr.append(test_stderr)
    status = (
        TestExecutionStatus.PASS
        if outcomes and all(item.status == "ok" for item in outcomes)
        else TestExecutionStatus.FAIL
    )
    return TraceResult(status, tuple(outcomes), tuple(calls), "\n".join(stdout), "\n".join(stderr))

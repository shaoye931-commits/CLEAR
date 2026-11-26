from __future__ import annotations

import ast
import json
import time
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Protocol

from src.analysis.contract import DependencyContract
from src.config import DATRConfig, INITIAL_PROMPT_VERSION
from src.models import GenerationTask
from src.reuse import extract_code


class GenerationStatus(str, Enum):
    SUCCESS = "success"
    EMPTY_CODE = "empty_code"
    INVALID_CODE = "invalid_code"
    REQUEST_FAILED = "request_failed"


@dataclass(frozen=True)
class GenerationModelConfig:
    model_name: str
    temperature: float
    top_p: float
    max_tokens: int

    @classmethod
    def from_datr_config(cls, config: DATRConfig) -> "GenerationModelConfig":
        return cls(config.model_name, config.temperature, config.top_p, config.max_tokens)


@dataclass(frozen=True)
class GenerationLLMResponse:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost: float | None = None
    request_attempts: int = 1
    finish_reason: str | None = None
    reasoning_tokens: int | None = None


class GenerationLLM(Protocol):
    def __call__(
        self, prompt: str, config: GenerationModelConfig
    ) -> GenerationLLMResponse: ...


@dataclass(frozen=True)
class GenerationResult:
    status: GenerationStatus
    code: str | None
    raw_response: str
    prompt: str
    error: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    estimated_cost: float | None
    elapsed_seconds: float
    call_count: int = 1
    reasoning_tokens: int | None = None


def _task_payload(task: GenerationTask, contract: DependencyContract) -> dict[str, object]:
    base = next(item for item in task.base_functions if item.name == contract.base_name)
    extended = next(item for item in task.extended_functions if item.name == contract.extended_name)
    return {
        "base_function_specification": task.base_problem,
        "extended_function_specification": task.extended_problem,
        "base_function": asdict(base),
        "extended_function": asdict(extended),
        "required_dependency": f"{contract.extended_name}->{contract.base_name}",
    }


def build_generation_prompt(
    task: GenerationTask,
    contract: DependencyContract,
    *,
    structural_feedback: tuple[str, ...] = (),
    history_summary: str | None = None,
    context_reset: bool = False,
) -> str:
    payload: dict[str, object] = _task_payload(task, contract)
    if structural_feedback:
        payload["structural_violations"] = structural_feedback
    if history_summary is not None:
        payload["summarized_execution_feedback"] = history_summary
    mode = "context reset" if context_reset else "dependency-guided generation"
    return (
        f"Prompt-Version: {INITIAL_PROMPT_VERSION}\n"
        f"Mode: {mode}\n"
        "Generate one complete Python program from the two function specifications.\n"
        "Reason through the base function, the extended function, and their dependency before coding.\n"
        "Define both required functions, preserve their specified interfaces, and make the extended function "
        "explicitly call the base function.\n"
        "Do not create or infer tests. Return exactly one fenced Python code block and no explanation.\n"
        "BEGIN_TASK\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}\n"
        "END_TASK"
    )


def _generate(
    prompt: str,
    llm: GenerationLLM,
    model_config: GenerationModelConfig,
) -> GenerationResult:
    started = time.perf_counter()
    try:
        response = llm(prompt, model_config)
    except Exception as error:
        return GenerationResult(
            GenerationStatus.REQUEST_FAILED,
            None,
            "",
            prompt,
            f"{type(error).__name__}: {error}",
            None,
            None,
            None,
            time.perf_counter() - started,
            getattr(error, "attempts", 1),
        )
    code, _ = extract_code(response.content)
    if not code.strip():
        status = GenerationStatus.EMPTY_CODE
        error = "model response contained no code"
        code = None
    else:
        try:
            ast.parse(code)
        except SyntaxError as parse_error:
            status = GenerationStatus.INVALID_CODE
            error = f"syntax_error: {parse_error.msg}"
        else:
            status = GenerationStatus.SUCCESS
            error = None
    return GenerationResult(
        status,
        code,
        response.content,
        prompt,
        error,
        response.prompt_tokens,
        response.completion_tokens,
        response.estimated_cost,
        time.perf_counter() - started,
        getattr(response, "request_attempts", 1),
        getattr(response, "reasoning_tokens", None),
    )


def generate_initial_candidate(
    task: GenerationTask,
    contract: DependencyContract,
    llm: GenerationLLM,
    model_config: GenerationModelConfig,
    *,
    structural_feedback: tuple[str, ...] = (),
) -> GenerationResult:
    prompt = build_generation_prompt(
        task, contract, structural_feedback=structural_feedback
    )
    return _generate(prompt, llm, model_config)


def reset_and_generate(
    task: GenerationTask,
    contract: DependencyContract,
    history_summary: str,
    llm: GenerationLLM,
    model_config: GenerationModelConfig,
    reset_temperature: float,
) -> GenerationResult:
    prompt = build_generation_prompt(
        task,
        contract,
        history_summary=history_summary,
        context_reset=True,
    )
    return _generate(prompt, llm, replace(model_config, temperature=reset_temperature))

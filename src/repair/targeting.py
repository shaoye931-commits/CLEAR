from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from typing import Protocol

from src.agents.diagnosis import DiagnosisRecord, FaultCategory
from src.analysis.contract import DependencyContract
from src.analysis.trace import TraceResult
from src.config import DATRConfig
from src.models import GenerationTask
from src.reuse import extract_code


@dataclass(frozen=True)
class ModificationConstraints:
    modification_targets: tuple[str, ...]
    preservation_targets: tuple[str, ...]
    diagnostic_guidance: str
    required_definitions: tuple[str, str]
    required_call: tuple[str, str]


@dataclass(frozen=True)
class RefinementModelConfig:
    model_name: str
    temperature: float
    top_p: float
    max_tokens: int

    @classmethod
    def from_datr_config(cls, config: DATRConfig) -> "RefinementModelConfig":
        return cls(config.model_name, config.temperature, config.top_p, config.max_tokens)


@dataclass(frozen=True)
class RefinementLLMResponse:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost: float | None = None
    request_attempts: int = 1
    reasoning_tokens: int | None = None


class RefinementLLM(Protocol):
    def __call__(
        self, prompt: str, config: RefinementModelConfig
    ) -> RefinementLLMResponse: ...


@dataclass(frozen=True)
class RefinementResult:
    code: str | None
    prompt: str
    raw_response: str
    error: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    estimated_cost: float | None
    elapsed_seconds: float
    call_count: int = 1
    reasoning_tokens: int | None = None


def update_frozen_functions(
    frozen_functions: set[str],
    diagnosis: DiagnosisRecord,
    contract: DependencyContract,
) -> set[str]:
    updated = set(frozen_functions)
    if diagnosis.fault_category is FaultCategory.BASE:
        updated.discard(contract.base_name)
        updated.add(contract.extended_name)
    elif diagnosis.fault_category is FaultCategory.EXT:
        updated.discard(contract.extended_name)
        updated.add(contract.base_name)
    elif diagnosis.fault_category is FaultCategory.CALL:
        updated.discard(contract.base_name)
        updated.discard(contract.extended_name)
    return updated


def build_constraints(
    diagnosis: DiagnosisRecord,
    contract: DependencyContract,
    frozen_functions: set[str],
) -> ModificationConstraints:
    category = diagnosis.fault_category
    if category is FaultCategory.BASE:
        modification = (contract.base_name,)
        preservation = (contract.extended_name,)
    elif category is FaultCategory.CALL:
        modification = (
            f"call sites {contract.extended_name}->{contract.base_name}",
            "interface definitions",
        )
        preservation = ("unrelated function logic",)
    elif category is FaultCategory.EXT:
        modification = (contract.extended_name,)
        preservation = (contract.base_name,)
    else:
        modification = (contract.base_name, contract.extended_name)
        preservation = tuple(sorted(frozen_functions))
    preservation = tuple(dict.fromkeys((*preservation, *sorted(frozen_functions))))
    return ModificationConstraints(
        modification,
        preservation,
        diagnosis.explanation,
        (contract.base_name, contract.extended_name),
        contract.dependency,
    )


def refine_candidate(
    task: GenerationTask,
    current_code: str,
    diagnosis: DiagnosisRecord,
    constraints: ModificationConstraints,
    contract: DependencyContract,
    trace: TraceResult,
    llm: RefinementLLM,
    model_config: RefinementModelConfig,
) -> RefinementResult:
    from src.repair.prompts import build_refinement_prompt

    prompt = build_refinement_prompt(
        task, current_code, diagnosis, constraints, contract, trace
    )
    started = time.perf_counter()
    try:
        response = llm(prompt, model_config)
    except Exception as error:
        return RefinementResult(
            None, prompt, "", f"{type(error).__name__}: {error}",
            None, None, None, time.perf_counter() - started,
            getattr(error, "attempts", 1), None,
        )
    code, _ = extract_code(response.content)
    error = None
    if not code.strip():
        code = None
        error = "model response contained no code"
    else:
        try:
            ast.parse(code)
        except SyntaxError as parse_error:
            error = f"syntax_error: {parse_error.msg}"
    return RefinementResult(
        code,
        prompt,
        response.content,
        error,
        response.prompt_tokens,
        response.completion_tokens,
        response.estimated_cost,
        time.perf_counter() - started,
        getattr(response, "request_attempts", 1),
        getattr(response, "reasoning_tokens", None),
    )

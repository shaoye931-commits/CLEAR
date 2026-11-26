from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Protocol

from src.analysis.contract import DependencyContract
from src.analysis.trace import TraceResult
from src.config import DIAGNOSIS_PROMPT_VERSION, DATRConfig
from src.models import GenerationTask


class FaultCategory(str, Enum):
    BASE = "BASE"
    CALL = "CALL"
    EXT = "EXT"
    UNDETERMINED = "UNDETERMINED"


@dataclass(frozen=True)
class DiagnosisRecord:
    fault_category: FaultCategory
    supporting_call_ids: tuple[int, ...]
    explanation: str


@dataclass(frozen=True)
class DiagnosisModelConfig:
    model_name: str
    temperature: float
    top_p: float
    max_tokens: int

    @classmethod
    def from_datr_config(cls, config: DATRConfig) -> "DiagnosisModelConfig":
        return cls(config.model_name, config.temperature, config.top_p, config.max_tokens)


@dataclass(frozen=True)
class DiagnosisLLMResponse:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost: float | None = None
    request_attempts: int = 1
    reasoning_tokens: int | None = None


class DiagnosisLLM(Protocol):
    def __call__(
        self, prompt: str, config: DiagnosisModelConfig
    ) -> DiagnosisLLMResponse: ...


@dataclass(frozen=True)
class DiagnosisRun:
    prompt: str
    raw_response: str
    diagnosis: DiagnosisRecord
    prompt_tokens: int | None
    completion_tokens: int | None
    estimated_cost: float | None
    elapsed_seconds: float
    call_count: int
    reasoning_tokens: int | None = None


def build_diagnosis_prompt(
    task: GenerationTask,
    contract: DependencyContract,
    candidate_code: str,
    trace: TraceResult,
) -> str:
    payload = {
        "base_function_specification": task.base_problem,
        "extended_function_specification": task.extended_problem,
        "required_dependency": f"{contract.extended_name}->{contract.base_name}",
        "candidate_program": candidate_code,
        "test_level_feedback": [asdict(item) for item in trace.test_outcomes],
        "call_level_evidence": [asdict(item) for item in trace.calls],
    }
    schema = {
        "fault_category": "BASE|CALL|EXT|UNDETERMINED",
        "supporting_call_ids": [1],
        "explanation": "evidence-grounded inconsistency",
    }
    return (
        f"Prompt-Version: {DIAGNOSIS_PROMPT_VERSION}\n"
        "You are CLEAR's fault diagnosis agent. Diagnose; do not modify code.\n"
        "For every observed base-function call, compare its arguments, status, and output with the base "
        "specification. Treat an exception as evidence, not by itself as proof of a base implementation fault.\n"
        "Then inspect whether the extended function supplied appropriate arguments and processed returned "
        "values according to its specification.\n"
        "Choose BASE for an inconsistent base implementation, CALL for an invocation or interface "
        "inconsistency, EXT for incorrect extended-function result processing, and UNDETERMINED when the "
        "available evidence is insufficient. Do not claim correctness for unobserved inputs.\n"
        "Cite supporting call IDs when available and do not invent calls.\n"
        "Return exactly one JSON object and no markdown.\n"
        f"JSON schema: {json.dumps(schema)}\n"
        "BEGIN_EVIDENCE\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}\n"
        "END_EVIDENCE"
    )


def _parse_diagnosis(raw: str, trace: TraceResult) -> DiagnosisRecord:
    try:
        payload = json.loads(raw)
        category = FaultCategory(payload["fault_category"])
        call_ids = payload.get("supporting_call_ids", [])
        explanation = payload["explanation"]
        known_ids = {item.call_id for item in trace.calls}
        if (
            not isinstance(call_ids, list)
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in call_ids)
            or any(item not in known_ids for item in call_ids)
            or not isinstance(explanation, str)
            or not explanation.strip()
        ):
            raise ValueError("invalid diagnosis fields")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return DiagnosisRecord(
            FaultCategory.UNDETERMINED,
            (),
            "The diagnosis response was invalid or unsupported by the recorded calls.",
        )
    return DiagnosisRecord(category, tuple(dict.fromkeys(call_ids)), explanation.strip())


def run_llm_diagnosis(
    task: GenerationTask,
    contract: DependencyContract,
    candidate_code: str,
    trace: TraceResult,
    llm: DiagnosisLLM,
    model_config: DiagnosisModelConfig,
) -> DiagnosisRun:
    prompt = build_diagnosis_prompt(task, contract, candidate_code, trace)
    started = time.perf_counter()
    try:
        response = llm(prompt, model_config)
    except Exception as error:
        elapsed = time.perf_counter() - started
        diagnosis = DiagnosisRecord(
            FaultCategory.UNDETERMINED,
            (),
            f"Diagnosis request failed: {type(error).__name__}: {error}",
        )
        return DiagnosisRun(
            prompt, "", diagnosis, None, None, None, elapsed,
            getattr(error, "attempts", 1), None,
        )
    return DiagnosisRun(
        prompt,
        response.content,
        _parse_diagnosis(response.content, trace),
        response.prompt_tokens,
        response.completion_tokens,
        response.estimated_cost,
        time.perf_counter() - started,
        getattr(response, "request_attempts", 1),
        getattr(response, "reasoning_tokens", None),
    )

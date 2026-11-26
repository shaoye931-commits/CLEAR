from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Callable

from src.agents.diagnosis import (
    DiagnosisModelConfig,
    DiagnosisRun,
    run_llm_diagnosis,
)
from src.agents.generation import (
    GenerationModelConfig,
    GenerationResult,
    generate_initial_candidate,
    reset_and_generate,
)
from src.analysis.ast_checks import StaticCheckResult, check_candidate
from src.analysis.contract import build_dependency_contract
from src.analysis.trace import TestExecutionStatus, TraceResult, collect_public_trace
from src.config import DATRConfig
from src.experiments.records import (
    CandidateSnapshot,
    IterationRecord,
    SealedCandidate,
    TaskRunRecord,
    to_jsonable,
)
from src.experiments.storage import RunStorage
from src.models import GenerationTask
from src.repair.targeting import (
    ModificationConstraints,
    RefinementModelConfig,
    RefinementResult,
    build_constraints,
    refine_candidate,
    update_frozen_functions,
)
from src.reuse import DockerUnavailableError


TraceCollector = Callable[..., TraceResult]


@dataclass(frozen=True)
class HistoryEntry:
    iteration: int
    structural_violations: tuple[str, ...] = ()
    test_feedback: tuple[object, ...] = ()
    call_evidence: tuple[object, ...] = ()
    diagnosis: object | None = None


@dataclass(frozen=True)
class PipelineResult:
    record: TaskRunRecord
    sealed_candidate: SealedCandidate | None


def summarize_history(history: list[HistoryEntry]) -> str:
    """Summarize evidence only; the current candidate is deliberately excluded."""
    return json.dumps(to_jsonable(history), ensure_ascii=False, separators=(",", ":"))


def run_clear_task(
    task: GenerationTask,
    config: DATRConfig,
    llm: object,
    *,
    trace_collector: TraceCollector = collect_public_trace,
    storage: RunStorage | None = None,
) -> PipelineResult:
    started = time.perf_counter()
    record = TaskRunRecord(
        task.task_id,
        task.dataset,
        config.model_name,
        config.run_id,
        asdict(config),
    )

    def persist(event: str) -> None:
        if storage is not None:
            storage.append_event(event, {"task_id": task.task_id})
            storage.save_task(record)

    def add_usage(result: object) -> None:
        record.usage.add(
            getattr(result, "prompt_tokens", None),
            getattr(result, "completion_tokens", None),
            getattr(result, "elapsed_seconds", 0.0),
            calls=getattr(result, "call_count", 1),
            reasoning_tokens=getattr(result, "reasoning_tokens", None),
            estimated_cost=getattr(result, "estimated_cost", None),
        )

    def seal(code: str, reason: str, public_status: str, iterations: int) -> PipelineResult:
        sealed = SealedCandidate.create(
            task.dataset,
            task.task_id,
            code,
            reason,
            public_status,
            iterations,
        )
        record.sealed_candidate = sealed
        record.snapshots.append(CandidateSnapshot.capture("final_candidate", code))
        record.terminal_status = reason
        record.total_seconds = time.perf_counter() - started
        persist("task_sealed")
        return PipelineResult(record, sealed)

    contract_result = build_dependency_contract(task)
    record.contract_result = contract_result
    if contract_result.contract is None:
        record.terminal_status = "contract_unresolved"
        record.failure_reasons.extend(contract_result.reasons)
        record.total_seconds = time.perf_counter() - started
        persist("task_failed")
        return PipelineResult(record, None)
    contract = contract_result.contract

    generation_config = GenerationModelConfig.from_datr_config(config)
    diagnosis_config = DiagnosisModelConfig.from_datr_config(config)
    refinement_config = RefinementModelConfig.from_datr_config(config)
    initial = generate_initial_candidate(task, contract, llm, generation_config)
    record.initial_generation = initial
    add_usage(initial)
    current_code = initial.code or ""
    record.snapshots.append(CandidateSnapshot.capture("initial_candidate", current_code))
    persist("initial_generated")

    history: list[HistoryEntry] = []
    frozen_functions: set[str] = set()
    for iteration in range(config.refinement_budget + 1):
        static = check_candidate(current_code, contract)
        iteration_record = IterationRecord(iteration, static)
        record.iterations.append(iteration_record)
        diagnosis_run: DiagnosisRun | None = None
        trace: TraceResult | None = None
        constraints: ModificationConstraints | None = None

        if not static.passed:
            violations = tuple(f"{item.code}: {item.message}" for item in static.issues)
            history.append(HistoryEntry(iteration, structural_violations=violations))
        else:
            try:
                trace = trace_collector(
                    task,
                    contract,
                    current_code,
                    image=config.docker_image,
                    time_limit_s=config.public_test_timeout_s,
                )
            except DockerUnavailableError as error:
                record.failure_reasons.append(str(error))
                iteration_record.action = "environment_blocked"
                return seal(current_code, "environment_blocked", "environment_error", iteration)
            iteration_record.trace = trace
            if trace.execution_status is TestExecutionStatus.PASS:
                iteration_record.action = "pass"
                return seal(current_code, "public_tests_passed", "pass", iteration)
            if trace.execution_status is TestExecutionStatus.INFRASTRUCTURE_ERROR:
                record.failure_reasons.append("call-level trace collection failed")
                iteration_record.action = "environment_blocked"
                return seal(current_code, "environment_blocked", "environment_error", iteration)

            diagnosis_run = run_llm_diagnosis(
                task,
                contract,
                current_code,
                trace,
                llm,
                diagnosis_config,
            )
            add_usage(diagnosis_run)
            frozen_functions = update_frozen_functions(
                frozen_functions, diagnosis_run.diagnosis, contract
            )
            constraints = build_constraints(
                diagnosis_run.diagnosis, contract, frozen_functions
            )
            iteration_record.diagnosis = diagnosis_run
            iteration_record.constraints = constraints
            history.append(
                HistoryEntry(
                    iteration,
                    test_feedback=trace.test_outcomes,
                    call_evidence=trace.calls,
                    diagnosis=diagnosis_run.diagnosis,
                )
            )

        if iteration == config.refinement_budget:
            iteration_record.action = "budget_exhausted"
            return seal(current_code, "refinement_budget_exhausted", "fail", iteration)

        if iteration == config.refinement_budget - 1:
            generated: GenerationResult | RefinementResult = reset_and_generate(
                task,
                contract,
                summarize_history(history),
                llm,
                generation_config,
                config.reset_temperature,
            )
            iteration_record.action = "context_reset"
        elif not static.passed:
            generated = generate_initial_candidate(
                task,
                contract,
                llm,
                generation_config,
                structural_feedback=tuple(
                    f"{item.code}: {item.message}" for item in static.issues
                ),
            )
            iteration_record.action = "structural_regeneration"
        else:
            assert diagnosis_run is not None and trace is not None and constraints is not None
            generated = refine_candidate(
                task,
                current_code,
                diagnosis_run.diagnosis,
                constraints,
                contract,
                trace,
                llm,
                refinement_config,
            )
            iteration_record.action = "constrained_refinement"

        iteration_record.generation = generated
        add_usage(generated)
        current_code = generated.code or ""
        record.snapshots.append(
            CandidateSnapshot.capture(f"candidate_{iteration + 1}", current_code)
        )
        persist(iteration_record.action)

    raise AssertionError("unreachable")

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from src.analysis.trace import (
    FunctionCallRecord,
    PublicTestOutcome,
    TestExecutionStatus,
    TraceResult,
)
from src.analysis.contract import build_dependency_contract
from src.config import (
    DIAGNOSIS_PROMPT_VERSION,
    INITIAL_PROMPT_VERSION,
    REFINEMENT_PROMPT_VERSION,
    DATRConfig,
)
from src.data import load_evaluation_task, load_generation_dataset
from src.evaluation import evaluate_sealed_candidate, missing_candidate_result
from src.experiments.records import SealedCandidate, to_jsonable
from src.experiments.storage import RunStorage
from src.llm import APICallBudget, LLMResponse, OpenAICompatibleClient
from src.models import FunctionMetadata, GenerationTask, TestCase
from src.pipeline import run_clear_task
from src.reuse import docker_image_available, load_original_environment


def _dataset(config: DATRConfig, name: str) -> tuple[str, Path]:
    if name == "humaneval":
        return "humaneval_pro", config.humaneval_path
    if name == "mbpp":
        return "mbpp_pro", config.mbpp_path
    raise ValueError("dataset must be humaneval or mbpp")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summary(candidate: SealedCandidate | None, evaluation: object, record: object) -> dict[str, object]:
    return {
        "dataset": getattr(record, "dataset"),
        "task_id": getattr(record, "task_id"),
        "model": getattr(record, "model"),
        "state": candidate.state if candidate else "NO_CANDIDATE",
        "seal_reason": candidate.seal_reason if candidate else None,
        "public_test_status": candidate.public_test_status if candidate else None,
        "refinement_iterations": candidate.refinement_iterations if candidate else 0,
        "held_out_passed": getattr(evaluation, "passed"),
        "held_out_passed_tests": getattr(evaluation, "passed_test_count"),
        "held_out_total_tests": getattr(evaluation, "held_out_test_count"),
        "total_tokens": getattr(record, "usage").total_tokens,
        "api_requests": getattr(record, "usage").call_count,
    }


def _inspect(args: argparse.Namespace) -> int:
    config = DATRConfig.from_environment()
    names = ("humaneval", "mbpp") if args.dataset == "all" else (args.dataset,)
    for selected in names:
        dataset_name, path = _dataset(config, selected)
        loaded = load_generation_dataset(path, dataset_name)
        report = loaded.report
        contracts = sum(
            build_dependency_contract(task).contract is not None for task in loaded.tasks
        )
        print(
            f"{dataset_name}: tasks={report.valid_count}, contracts={contracts}, "
            f"public_tests={report.public_tests}, "
            f"held_out_tests={report.held_out_tests}, filtered={dict(report.filtered_reasons)}, "
            f"issues={dict(report.issues)}"
        )
    print(f"docker_image_ready={docker_image_available(config.docker_image)}")
    print(f"method_version={config.method_version}")
    return 0


def _mock() -> int:
    task = GenerationTask(
        "mock",
        "demo",
        "Implement def base(x): returning twice x.",
        "Implement def extended(values): call base for each item and return the results.",
        (FunctionMetadata("base", "base(x)", ("x",)),),
        (FunctionMetadata("extended", "extended(values)", ("values",)),),
        (
            TestCase(1, "assert extended([1, 2]) == [2, 4]"),
            TestCase(2, "assert extended([]) == []"),
        ),
    )
    bad = "def base(x):\n    return 0\n\ndef extended(values):\n    return [base(x) for x in values]\n"
    good = bad.replace("return 0", "return x * 2")

    def llm(prompt, config):
        if "fault diagnosis agent" in prompt:
            return LLMResponse(
                '{"fault_category":"BASE","supporting_call_ids":[1,2],'
                '"explanation":"Observed base outputs contradict the base specification."}',
                10,
                10,
            )
        if "Refine the current candidate" in prompt:
            return LLMResponse(f"```python\n{good}```", 10, 10)
        return LLMResponse(f"```python\n{bad}```", 10, 10)

    def trace_collector(task, contract, code, **kwargs):
        if "x * 2" in code:
            return TraceResult(
                TestExecutionStatus.PASS,
                (PublicTestOutcome(1, "ok", None, None), PublicTestOutcome(2, "ok", None, None)),
                (),
            )
        return TraceResult(
            TestExecutionStatus.FAIL,
            (PublicTestOutcome(1, "fail", "AssertionError", ""), PublicTestOutcome(2, "ok", None, None)),
            (
                FunctionCallRecord(1, "base", "[1]", "{}", "ok", "0", None, None),
                FunctionCallRecord(2, "base", "[2]", "{}", "ok", "0", None, None),
            ),
        )

    result = run_clear_task(
        task,
        DATRConfig(model_name="mock", run_id="mock"),
        llm,
        trace_collector=trace_collector,
    )
    print(json.dumps(result.record.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.sealed_candidate and result.sealed_candidate.public_test_status == "pass" else 1


def _run(args: argparse.Namespace) -> int:
    if not args.allow_api:
        raise RuntimeError("run mode requires --allow-api")
    required = {
        "--run-id": args.run_id,
        "--model": args.model or os.getenv("CLEAR_MODEL"),
        "--api-endpoint": args.api_endpoint or os.getenv("CLEAR_API_ENDPOINT"),
        "--model-kind": args.model_kind,
        "--max-api-requests": args.max_api_requests,
        "--max-total-tokens": args.max_total_tokens,
    }
    missing = [name for name, value in required.items() if value in (None, "")]
    if missing:
        raise RuntimeError("missing required arguments: " + ", ".join(missing))
    api_key_env = args.api_key_env or os.getenv("CLEAR_API_KEY_ENV", "CLEAR_API_KEY")
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"API key environment variable is missing: {api_key_env}")
    temperature = 0.2 if args.model_kind == "proprietary" else 0.0
    config = DATRConfig.from_environment(
        model_name=required["--model"],
        api_endpoint=required["--api-endpoint"],
        api_key_env=api_key_env,
        run_id=args.run_id,
        allow_real_api=True,
        temperature=temperature,
    )
    if not docker_image_available(config.docker_image):
        raise RuntimeError(f"Docker daemon or {config.docker_image} is unavailable")
    dataset_name, path = _dataset(config, args.dataset)
    loaded = load_generation_dataset(path, dataset_name)
    if args.task_id is None:
        tasks = loaded.tasks
    else:
        tasks = tuple(item for item in loaded.tasks if str(item.task_id) == args.task_id)
        if not tasks:
            raise RuntimeError(f"task not found: {args.task_id}")
    metadata = {
        "method_version": config.method_version,
        "run_id": config.run_id,
        "dataset": dataset_name,
        "task_ids": [task.task_id for task in tasks],
        "model": config.model_name,
        "model_kind": args.model_kind,
        "data_source_hash": _file_hash(path),
        "split_protocol": "first-two-public-rest-held-out",
        "prompt_versions": {
            "initial": INITIAL_PROMPT_VERSION,
            "diagnosis": DIAGNOSIS_PROMPT_VERSION,
            "refinement": REFINEMENT_PROMPT_VERSION,
        },
        "config": to_jsonable(config),
    }
    storage = RunStorage.create(config.output_root, config.run_id, metadata)
    budget = APICallBudget(args.max_api_requests, args.max_total_tokens)
    client = OpenAICompatibleClient(
        endpoint=config.api_endpoint,
        api_key=api_key,
        allow_real_api=True,
        timeout_s=config.request_timeout_s,
        max_retries=config.request_retries,
        audit_hook=lambda event, payload: storage.append_event(event, payload),
        budget=budget,
    )
    completed = []
    for task in tasks:
        result = run_clear_task(task, config, client, storage=storage)
        evaluation_task = load_evaluation_task(path, dataset_name, task.task_id)
        evaluation = (
            evaluate_sealed_candidate(
                result.sealed_candidate,
                evaluation_task,
                image=config.docker_image,
                time_limit_s=config.public_test_timeout_s,
            )
            if result.sealed_candidate
            else missing_candidate_result(evaluation_task)
        )
        result.record.evaluation = evaluation
        storage.save_evaluation(task.task_id, evaluation)
        storage.mark_task_complete(result.record)
        completed.append((result, evaluation))
    if len(completed) == 1:
        result, evaluation = completed[0]
        output = _summary(result.sealed_candidate, evaluation, result.record)
    else:
        successful = [
            result for result, evaluation in completed
            if evaluation.passed and result.sealed_candidate is not None
        ]
        output = {
            "dataset": dataset_name,
            "model": config.model_name,
            "tasks": len(completed),
            "successful_tasks": len(successful),
            "pass_at_1_percent": len(successful) / len(completed) * 100,
            "average_iterations": (
                sum(result.sealed_candidate.refinement_iterations for result in successful)
                / len(successful)
                if successful else 0.0
            ),
            "average_tokens": sum(
                result.record.usage.total_tokens for result, _ in completed
            ) / len(completed),
            "average_runtime_seconds": sum(
                result.record.total_seconds for result, _ in completed
            ) / len(completed),
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    load_original_environment()
    parser = argparse.ArgumentParser(description="CLEAR reproduction runner")
    parser.add_argument("--mode", choices=("inspect", "mock", "run"), default="inspect")
    parser.add_argument("--dataset", choices=("all", "humaneval", "mbpp"), default="all")
    parser.add_argument("--task-id")
    parser.add_argument("--run-id")
    parser.add_argument("--model")
    parser.add_argument("--model-kind", choices=("open-weight", "proprietary"))
    parser.add_argument("--api-endpoint")
    parser.add_argument("--api-key-env")
    parser.add_argument("--max-api-requests", type=int)
    parser.add_argument("--max-total-tokens", type=int)
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "inspect":
            return _inspect(args)
        if args.mode == "mock":
            return _mock()
        if args.dataset == "all":
            raise RuntimeError("run mode requires one dataset")
        return _run(args)
    except Exception as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

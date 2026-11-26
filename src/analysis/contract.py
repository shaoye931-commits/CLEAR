from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.models import GenerationTask, TaskId


class ContractStatus(str, Enum):
    SUCCESS = "success"
    MISSING_INFORMATION = "missing_information"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class DependencyContract:
    base_name: str
    extended_name: str
    dependency: tuple[str, str]


@dataclass(frozen=True)
class ContractEvidence:
    source: str
    value: str


@dataclass(frozen=True)
class ContractBuildResult:
    task_id: TaskId
    status: ContractStatus
    contract: DependencyContract | None
    reasons: tuple[str, ...]
    evidence: tuple[ContractEvidence, ...]


def build_dependency_contract(task: GenerationTask) -> ContractBuildResult:
    reasons: list[str] = []
    if task.base_problem is None:
        reasons.append("missing_base_problem")
    if not task.base_functions:
        reasons.append("missing_base_function_declaration")
    if not task.extended_functions:
        reasons.append("missing_extended_function_declaration")
    if reasons:
        return ContractBuildResult(
            task.task_id,
            ContractStatus.MISSING_INFORMATION,
            None,
            tuple(reasons),
            (),
        )

    # Benchmark prompts may define helpers before the requested function; the target
    # declaration is the final one in both specifications.
    base = task.base_functions[-1]
    extended = task.extended_functions[-1]
    evidence = (
        ContractEvidence("base_problem:function_declaration", base.signature),
        ContractEvidence("extended_problem:function_declaration", extended.signature),
        ContractEvidence("dataset_role_pairing", f"{extended.name}->{base.name}"),
    )
    if base.name == extended.name:
        return ContractBuildResult(
            task.task_id,
            ContractStatus.AMBIGUOUS,
            None,
            ("base_and_extended_names_are_identical",),
            evidence,
        )
    contract = DependencyContract(
        base.name,
        extended.name,
        (extended.name, base.name),
    )
    return ContractBuildResult(
        task.task_id,
        ContractStatus.SUCCESS,
        contract,
        (),
        evidence,
    )

"""
消融实验版本：禁用失败历史注入功能
此配置运行完整的 TD-IR 流程，但特意禁用了"失败历史注入"功能。
每次修复迭代时，模型不会收到之前失败轮次的历史信息，仅依赖当前轮次的错误诊断。
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_environment
from .llm_handler import generate_code
from .mbpp_utils import MbppTask, build_test_script_from_list, read_mbpp_data
from .sandbox_executor import SandboxResult, run_in_sandbox
from .prompt_factory import (
    build_initial_prompt,
    build_initial_prompt_with_cot,
    build_feedback_prompt,
    build_guided_diagnostics_prompt,
    build_sanity_check_prompt,
    parse_error_diagnostics,
    _ensure_typing_imports,
)


@dataclass
class IterationLog:
    iteration: int
    prompt: str
    code: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    failed_assert: Optional[str] = None
    actual_output: Optional[str] = None
    expected_output: Optional[str] = None


@dataclass
class TaskLog:
    task_id: int
    problem: str
    iterations: List[IterationLog]
    final_status: str  # "success" | "fail" | "pass_by_review"


def process_task_ablation(
    task: MbppTask,
    *,
    max_iters: int,
    image: str,
    use_cot: bool = True,
    use_reflection: bool = True,
    use_failure_history: bool = False,  # ⭐ 消融实验：禁用失败历史注入
) -> TaskLog:
    """
    处理单个任务，支持思维链和引导式诊断，但禁用失败历史注入（消融实验）。
    
    Args:
        use_cot: 是否使用思维链（Chain of Thought）
        use_reflection: 是否使用引导式诊断（Guided Diagnostics）
        use_failure_history: 是否使用失败历史注入（消融实验：设置为False）
    """
    iterations: List[IterationLog] = []
    failure_history: List[Dict[str, Any]] = []  # 失败历史（消融实验中不使用）
    assertion_failure_count = 0  # 断言失败计数，用于触发测试用例审查

    # First attempt with initial prompt (使用思维链版本)
    if use_cot:
        prompt = build_initial_prompt_with_cot(task.prompt, task.test_list)
        gen = generate_code(prompt, use_cot=True)
    else:
        prompt = build_initial_prompt(task.prompt)
        gen = generate_code(prompt)
    code = gen["code"]
    # 自动添加缺失的 typing import
    code = _ensure_typing_imports(code)

    # 使用 test_list 进行迭代过程中的测试
    tests_script = build_test_script_from_list(task.test_list)

    for i in range(max_iters):
        result: SandboxResult = run_in_sandbox(code, tests_script, image=image)
        
        # 解析错误诊断信息
        error_diagnostics = parse_error_diagnostics(result.stderr or result.stdout or "", result.exit_code)
        
        # 创建迭代日志
        iteration_log = IterationLog(
            iteration=i + 1,
            prompt=prompt,
            code=code,
            success=result.success,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            failed_assert=error_diagnostics.get("failed_assert"),
            actual_output=error_diagnostics.get("actual_output"),
            expected_output=error_diagnostics.get("expected_output"),
        )
        iterations.append(iteration_log)
        
        if result.success:
            return TaskLog(
                task_id=task.task_id,
                problem=task.prompt,
                iterations=iterations,
                final_status="success",
            )

        # 记录失败历史（消融实验中虽然记录，但不注入到提示词中）
        if error_diagnostics.get("error_type") == "AssertionError":
            assertion_failure_count += 1
            failure_history.append({
                "code": code,
                "error_type": error_diagnostics.get("error_type"),
                "failed_assert": error_diagnostics.get("failed_assert"),
                "actual_output": error_diagnostics.get("actual_output"),
                "expected_output": error_diagnostics.get("expected_output"),
                "error_message": result.stderr or result.stdout or "",
            })
            
            # 触发测试用例审查（当断言失败达到2次时）
            if assertion_failure_count >= 2 and error_diagnostics.get("actual_output") and error_diagnostics.get("expected_output"):
                sanity_check_prompt = build_sanity_check_prompt(
                    task.prompt,
                    error_diagnostics.get("actual_output"),
                    error_diagnostics.get("expected_output")
                )
                sanity_response = generate_code(sanity_check_prompt, use_cot=False)
                sanity_result_text = (sanity_response.get("rationale", "") + " " + sanity_response.get("code", "") + " " + sanity_response.get("raw_response", "")).strip()
                
                # 检查LLM是否认为实际输出是正确的（更灵活的匹配）
                sanity_result_lower = sanity_result_text.lower()
                if "output a is correct" in sanity_result_lower or sanity_result_text.strip().startswith("Output A is correct"):
                    # 测试用例可能有问题，标记为通过审查
                    return TaskLog(
                        task_id=task.task_id,
                        problem=task.prompt,
                        iterations=iterations,
                        final_status="pass_by_review",
                    )
        else:
            failure_history.append({
                "code": code,
                "error_type": error_diagnostics.get("error_type"),
                "error_message": result.stderr or result.stdout or "",
            })

        # Build feedback prompt and try again
        # ⭐ 消融实验：禁用失败历史注入，传入空列表
        if use_reflection:
            if use_failure_history:
                # 正常版本：使用失败历史注入
                prompt = build_guided_diagnostics_prompt(
                    task.prompt,
                    code,
                    error_diagnostics,
                    failure_history,  # 传入失败历史
                    task.test_list
                )
            else:
                # 消融实验版本：禁用失败历史注入
                prompt = build_guided_diagnostics_prompt(
                    task.prompt,
                    code,
                    error_diagnostics,
                    [],  # ⭐ 传入空列表，禁用失败历史注入
                    task.test_list
                )
            gen = generate_code(prompt, use_cot=True)
        else:
            prompt = build_feedback_prompt(task.prompt, code, result.stderr or result.stdout, task.test_list)
            gen = generate_code(prompt)
        code = gen["code"]
        # 自动添加缺失的 typing import
        code = _ensure_typing_imports(code)

    # 所有迭代都失败
    return TaskLog(
        task_id=task.task_id,
        problem=task.prompt,
        iterations=iterations,
        final_status="fail",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TD-IR ablation experiment: Disable Failure History Injection"
    )
    parser.add_argument("--data", type=Path, default=Path("data/mbpp.jsonl"))
    parser.add_argument("--results_dir", type=Path, default=Path("results"))
    parser.add_argument("--max_iters", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="Limit number of problems to run")
    parser.add_argument("--image", type=str, default="tdir-sandbox:latest")
    parser.add_argument("--use-cot", action="store_true", default=True, help="Use Chain of Thought")
    parser.add_argument("--use-reflection", action="store_true", default=True, help="Use Guided Diagnostics")
    args = parser.parse_args()

    load_environment()

    run_id = time.strftime("%Y%m%d_%H%M%S")
    args.results_dir.mkdir(parents=True, exist_ok=True)
    # ⭐ 消融实验：在文件名中标注
    out_path = args.results_dir / f"tdir_ablation_no_history_{run_id}.jsonl"

    print("=" * 80)
    print("TD-IR 消融实验：禁用失败历史注入")
    print("=" * 80)
    print(f"数据文件: {args.data}")
    print(f"最大迭代次数: {args.max_iters}")
    print(f"任务限制: {args.limit if args.limit else '全部'}")
    print(f"使用思维链: {args.use_cot}")
    print(f"使用引导式诊断: {args.use_reflection}")
    print(f"失败历史注入: ❌ 已禁用（消融实验）")
    print(f"结果文件: {out_path}")
    print("=" * 80)
    print()

    count = 0
    with out_path.open("w", encoding="utf-8") as out:
        for task in read_mbpp_data(args.data):
            if args.limit and count >= args.limit:
                break
            print(f"Processing task {task.task_id}...")
            tlog = process_task_ablation(
                task,
                max_iters=args.max_iters,
                image=args.image,
                use_cot=args.use_cot,
                use_reflection=args.use_reflection,
                use_failure_history=False,  # ⭐ 消融实验：禁用失败历史注入
            )
            out.write(json.dumps({
                "task_id": tlog.task_id,
                "problem": tlog.problem,
                "final_status": tlog.final_status,
                "iterations": [asdict(it) for it in tlog.iterations],
            }, ensure_ascii=False) + "\n")
            out.flush()
            count += 1

    print()
    print("=" * 80)
    print(f"消融实验完成！结果已保存到: {out_path}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


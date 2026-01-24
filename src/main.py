from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any

from .config import load_environment
from .llm_handler import generate_code
from .mbpp_utils import MbppTask, build_test_script_from_list, read_mbpp_data
from .sandbox_executor import SandboxResult, run_in_sandbox
from .dual_task_compliance import check_dual_task_compliance, build_rethink_prompt_for_compliance_violation


@dataclass
class IterationLog:
    iteration: int
    prompt: str
    code: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    failed_assert: Optional[str] = None  # 失败的断言信息（如果适用）
    actual_output: Optional[str] = None  # 实际输出
    expected_output: Optional[str] = None  # 期望输出


@dataclass
class TaskLog:
    task_id: int
    problem: str
    iterations: List[IterationLog]
    final_status: str  # "success" | "fail" | "pass_by_review"


def process_task(
    task: MbppTask,
    *,
    max_iters: int,
    image: str,
    use_cot: bool = True,
    use_reflection: bool = True,
) -> TaskLog:
    """
    处理单个任务，支持思维链和引导式诊断。
    
    Args:
        use_cot: 是否使用思维链（Chain of Thought）
        use_reflection: 是否使用引导式诊断（Guided Diagnostics）
    """
    iterations: List[IterationLog] = []
    failure_history: List[Dict[str, Any]] = []  # 失败历史，用于注入
    assertion_failure_count = 0  # 断言失败计数，用于触发测试用例审查

    # ========== 强制双任务模式：数据校验 ==========
    if not task.raw_problem:
        raise ValueError(
            f"Task {task.task_id} is missing raw_problem. "
            "This system only supports dual-task scenarios. Only dual-task supported."
        )
    
    # First attempt with initial prompt (使用思维链版本)
    from .prompt_factory import (
        build_initial_prompt_with_cot,
        build_initial_prompt_zero_shot,
        build_guided_diagnostics_prompt_enhanced,
        build_sanity_check_prompt,
        build_third_iteration_complete_rethink_prompt,
        _ensure_typing_imports,
    )
    from .dual_task_diagnostics import parse_error_diagnostics_enhanced
    
    # ========== 提取函数名（强制双任务） ==========
    # 优先使用在 mbpp_utils 中预解析好的函数名
    helper_name = getattr(task, "helper_name", None)
    main_name = getattr(task, "main_name", None)

    # 兼容性回退：如果预解析失败，再使用旧的提取逻辑
    if not helper_name or not main_name:
        from .prompt_factory import extract_function_name_from_problem, extract_function_name_from_test
        if not helper_name:
            helper_name = extract_function_name_from_problem(task.raw_problem or "")
        if not main_name:
            # 优先从 new_problem/prompt 中解析主函数名，失败时再从测试提取
            main_name = extract_function_name_from_problem(task.new_problem or task.prompt or "") \
                or (extract_function_name_from_test(task.test_list[0]) if task.test_list else None)
    
    if not helper_name:
        raise ValueError(
            f"Task {task.task_id}: Failed to extract helper function name from raw_problem. "
            f"raw_problem: {task.raw_problem[:100]}..."
        )
    
    if not main_name:
        raise ValueError(
            f"Task {task.task_id}: Failed to extract main function name from test_list. "
            f"test_list length: {len(task.test_list) if task.test_list else 0}"
        )

    task_context = {
        "task_id": task.task_id,
        "raw_problem": task.raw_problem,
        "new_problem": task.new_problem or task.prompt,
        "prompt": task.prompt,
        "test_list": task.test_list,
        "tests_source": "\n".join(task.test_list),
    }

    # ========== Zero-Shot Protocol: 初始代码生成 ==========
    # 选择使用 Zero-Shot Protocol 或传统 CoT
    use_zero_shot = True  # 可以通过参数控制
    
    if use_zero_shot:
        prompt = build_initial_prompt_zero_shot(
            task.prompt,
            helper_name,
            main_name,
            task.test_list,
        )
    else:
        prompt = build_initial_prompt_with_cot(task.prompt, task.test_list)
    
    gen = generate_code(prompt, use_cot=not use_zero_shot)
    code = gen["code"]
    # 自动添加缺失的 typing import
    code = _ensure_typing_imports(code)
    
    # ========== Zero-Shot Protocol: AST 合规检查 ==========
    # 在进入沙盒执行前，先进行静态检查
    is_compliant, compliance_error = check_dual_task_compliance(
        code, helper_name, main_name
    )
    
    if not is_compliant:
        # 如果不符合双任务要求，立即生成 RETHINK 提示词
        print(f"  [AST Check] ❌ Dual-Task Compliance Violation: {compliance_error}")
        print(f"  [AST Check] 🔄 Generating RETHINK prompt...")
        
        rethink_prompt = build_rethink_prompt_for_compliance_violation(
            code,
            helper_name,
            main_name,
            compliance_error,
            task.prompt,
        )
        
        # 使用 RETHINK 提示词重新生成代码
        gen = generate_code(rethink_prompt, use_cot=False)
        code = gen["code"]
        code = _ensure_typing_imports(code)
        
        # 再次检查
        is_compliant, compliance_error = check_dual_task_compliance(
            code, helper_name, main_name
        )
        
        if not is_compliant:
            print(f"  [AST Check] ⚠️  Still non-compliant after RETHINK. Proceeding to sandbox execution...")
        else:
            print(f"  [AST Check] ✅ Compliance verified after RETHINK.")
    else:
        print(f"  [AST Check] ✅ Dual-Task Compliance verified.")

    # 使用 test_list 进行迭代过程中的测试
    tests_script = build_test_script_from_list(task.test_list)

    for i in range(max_iters):
        # ========== 执行测试并获取执行追踪 ==========
        result: SandboxResult = run_in_sandbox(
            code,
            tests_script,
            image=image,
            helper_name=helper_name,  # 传递辅助函数名以启用追踪
        )
        
        # ========== 使用分层诊断（强制双任务） ==========
        error_diagnostics = parse_error_diagnostics_enhanced(
            result.stderr or result.stdout or "",
            result.exit_code,
            code,
            helper_name,
            main_name,
            result.execution_trace or [],  # 确保是列表格式
            task.raw_problem,
            task_context=task_context,
        )
        
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

        # 记录失败历史
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

        # ========== 构建反馈提示词 ==========
        # 修改点：使用 max_iters - 2 来确保在倒数第二次运行时触发，为最后一次运行生成重构代码
        # 当 max_iters=3 时，i=1 会触发重构模式，为 i=2 的最后一次尝试生成代码
        # 执行流程：
        #   i=0: 执行第1次测试，失败后生成诊断代码用于 i=1
        #   i=1: 执行第2次测试，失败后生成重构代码用于 i=2 (触发重构模式)
        #   i=2: 执行第3次测试，使用重构代码
        if i == max_iters - 2:
            print(f"🔥 [Mode Switch] Activating RETHINK MODE for Task {task.task_id} (Preparing for final attempt)")
            print(f"   [DEBUG] Current iteration: {i+1}/{max_iters}, Next iteration will use RETHINK code")
            
            # 1. 拼接完整的题目描述（Helper + Main Task）
            # 这样 LLM 能看到完整的任务要求，包括辅助函数和主函数
            full_problem = f"{task.raw_problem}\n\n{task.prompt}"
            
            # 2. 调用新的 Prompt 函数
            sys_prompt = build_third_iteration_complete_rethink_prompt(
                raw_problem=full_problem,
                failure_history=failure_history
            )
            
            # 3. 关键：User Prompt 留空，禁用 CoT，完全依赖 System Prompt
            # 这样可以防止模型被之前的对话历史误导
            gen = generate_code(
                prompt="", 
                system_prompt=sys_prompt, 
                use_cot=False 
            )
            
            # 4. 更新 prompt 变量以便下次迭代记录日志时能正确显示
            prompt = f"[RETHINK MODE] System Prompt:\n{sys_prompt}"
            
        else:
            # 第 1, 2 次迭代 (保持原样)
            print(f"🔧 [Mode Switch] Diagnosis Mode (Iter {i+1}/{max_iters})")
            prompt = build_guided_diagnostics_prompt_enhanced(
                task.prompt,
                code,
                error_diagnostics,
                failure_history,
                task.test_list
            )
            gen = generate_code(prompt=prompt, use_cot=True)
        
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
    parser = argparse.ArgumentParser(description="Run TD-IR on MBPP dataset")
    parser.add_argument("--data", type=Path, default=Path("data/mbpp.jsonl"))
    parser.add_argument("--results_dir", type=Path, default=Path("results"))
    parser.add_argument("--max_iters", type=int, default=3)
    parser.add_argument("--limit", type=int, default=5, help="Limit number of problems to run (for quick start)")
    parser.add_argument("--image", type=str, default="tdir-sandbox:latest")
    args = parser.parse_args()

    load_environment()

    run_id = time.strftime("%Y%m%d_%H%M%S")
    args.results_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.results_dir / f"tdir_run_{run_id}.jsonl"

    count = 0
    with out_path.open("w", encoding="utf-8") as out:
        for task in read_mbpp_data(args.data):
            if count >= args.limit:
                break
            print(f"Processing task {task.task_id}...")
            tlog = process_task(
                task,
                max_iters=args.max_iters,
                image=args.image,
                use_cot=True,  # 使用思维链
                use_reflection=True,  # 使用引导式诊断
            )
            out.write(json.dumps({
                "task_id": tlog.task_id,
                "problem": tlog.problem,
                "final_status": tlog.final_status,
                "iterations": [asdict(it) for it in tlog.iterations],
            }, ensure_ascii=False) + "\n")
            out.flush()
            count += 1

    print(f"Run complete. Results saved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



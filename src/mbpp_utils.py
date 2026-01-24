from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Iterator, List, Optional, Tuple


@dataclass(frozen=True)
class MbppTask:
    task_id: int
    prompt: str
    test_list: List[str]
    raw_problem: Optional[str] = None
    new_problem: Optional[str] = None
    # 预解析得到的函数名（双任务模式中用于 helper/main 定位）
    helper_name: Optional[str] = None
    main_name: Optional[str] = None


def _extract_asserts_from_test_code(test_code: str) -> List[str]:
    asserts: List[str] = []
    for line in test_code.split("\n"):
        line = line.strip()
        if line.startswith("assert"):
            asserts.append(line)
    return asserts


_DEF_PATTERN = re.compile(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")
_ASSERT_CALL_PATTERN = re.compile(r"assert\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")


def _extract_function_name_from_source(source: str) -> Optional[str]:
    """
    从源码字符串中提取函数名。
    优先用于 new_problem/raw_problem 中的 `def func_name(...):`。
    """
    if not source:
        return None
    m = _DEF_PATTERN.search(source)
    if m:
        return m.group(1)
    return None


def _extract_function_name_from_tests(test_list: List[str]) -> Optional[str]:
    """
    备选策略：从测试用例列表中提取主函数名。
    模式: assert func_name(...)
    """
    for line in test_list or []:
        m = _ASSERT_CALL_PATTERN.search(line)
        if m:
            return m.group(1)
    return None


def _infer_function_names(
    raw_problem: str,
    new_problem: str,
    test_list: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    推断 helper_name 和 main_name：
    - helper_name: 优先从 raw_problem 中的 def ... 提取。
    - main_name:   优先从 new_problem (或 prompt) 中的 def ... 提取，
                   如失败，则回退到从 test_list 的 assert func(...) 中提取。
    """
    helper_name = _extract_function_name_from_source(raw_problem)
    main_name = _extract_function_name_from_source(new_problem)
    if not main_name:
        main_name = _extract_function_name_from_tests(test_list)
    return helper_name, main_name


def read_mbpp_pro_json(path: Path) -> Iterator[MbppTask]:
    """
    读取 mbpp_pro.json / humaneval_pro.json 格式的数据集。
    两者均为 JSON 数组，每个元素包含 id/new_problem/test_code 字段。
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:
        task_id = int(item.get("id", 0))
        raw_problem = str(item.get("raw_problem", "") or "").strip()
        new_problem = str(item.get("new_problem", "") or item.get("prompt", "")).strip()
        test_code = str(item.get("test_code", "")).strip()
        test_list = _extract_asserts_from_test_code(test_code)

        # 先依据 Raw/New Problem + tests 推断 helper/main 函数名
        helper_name, main_name = _infer_function_names(raw_problem, new_problem, test_list)

        if raw_problem:
            prompt = dedent(
                f"""
                You must solve two linked tasks in a single submission.

                ## Raw Problem (Helper Function)

                {raw_problem}

                ## New Problem (Primary Goal)

                {new_problem}

                ### Implementation Guidelines

                - First, implement the function required by the Raw Problem exactly as specified (same function name, signature, and behavior).
                - Keep this raw helper defined at module scope; do not inline or remove it.
                - When implementing the New Problem's function, call the raw helper to reuse its behavior wherever appropriate. Tests only exercise the New Problem, but they assume it leverages the raw helper.
                - Additional helper functions are allowed, but the raw helper must exist and be referenced in the final solution.
                """
            ).strip()
        else:
            prompt = new_problem

        yield MbppTask(
            task_id=task_id,
            prompt=prompt,
            test_list=test_list,
            raw_problem=raw_problem or None,
            new_problem=new_problem or None,
            helper_name=helper_name,
            main_name=main_name,
        )


def read_mbpp_data(path: Path) -> Iterator[MbppTask]:
    """
    仅支持 JSON 数组形式的数据集（mbpp_pro.json / humaneval_pro.json）。
    """
    yield from read_mbpp_pro_json(path)


def build_test_script_from_list(test_list: Iterable[str]) -> str:
    body = "\n".join(test_list)
    return (
        "from solution import *\n"
        + body
        + "\nprint('ALL_TESTS_PASSED')\n"
    )



"""
Zero-Shot Protocol: Dual-Task Compliance Checker

通过 AST 静态分析，强制要求 Main 函数必须调用 Helper 函数。
这是 Zero-Shot 模式下的最后一道防线，在代码进入沙盒执行前进行验证。
"""

import ast
from typing import Tuple, Optional, List


def check_dual_task_compliance(
    code_str: str, 
    helper_name: str, 
    main_name: str
) -> Tuple[bool, Optional[str]]:
    """
    Zero-Shot 模式下的最后一道防线。
    通过 AST 分析，强制要求 Main 函数必须调用 Helper 函数。
    
    Args:
        code_str: 生成的代码字符串
        helper_name: 辅助函数名称
        main_name: 主函数名称
        
    Returns:
        (is_compliant, error_message)
        - is_compliant: True 如果符合双任务要求，False 否则
        - error_message: 如果不符合，返回详细的错误信息；如果符合，返回 None
    """
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return False, f"Syntax Error: {e}"

    main_func_node: Optional[ast.FunctionDef] = None
    helper_func_node: Optional[ast.FunctionDef] = None

    # 1. 找到两个函数的定义
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name == main_name:
                main_func_node = node
            elif node.name == helper_name:
                helper_func_node = node

    if not helper_func_node:
        return False, f"Missing Helper Function: '{helper_name}' is not defined."
    
    if not main_func_node:
        return False, f"Missing Main Function: '{main_name}' is not defined."

    # 2. 检查 Main 函数内部是否有对 Helper 的调用
    helper_called = False
    call_locations: List[int] = []
    
    for node in ast.walk(main_func_node):
        if isinstance(node, ast.Call):
            # 检查直接函数调用: helper_name(...)
            if isinstance(node.func, ast.Name) and node.func.id == helper_name:
                helper_called = True
                call_locations.append(node.lineno if hasattr(node, 'lineno') else 0)
            
            # 检查属性调用: obj.helper_name(...) 或 module.helper_name(...)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == helper_name:
                helper_called = True
                call_locations.append(node.lineno if hasattr(node, 'lineno') else 0)
            
            # 检查通过变量间接调用（如果变量名匹配）
            elif isinstance(node.func, ast.Name):
                # 这里可以扩展检查变量是否指向 helper_name
                pass

    if not helper_called:
        return False, (
            f"Dual-Task Violation: The function '{main_name}' implements the logic internally "
            f"instead of calling '{helper_name}'. You MUST call '{helper_name}' inside '{main_name}'."
        )

    return True, None


def build_rethink_prompt_for_compliance_violation(
    code: str,
    helper_name: str,
    main_name: str,
    error_message: str,
    original_prompt: str,
) -> str:
    """
    当代码未通过双任务合规检查时，生成 RETHINK 提示词。
    
    Args:
        code: 失败的代码
        helper_name: 辅助函数名称
        main_name: 主函数名称
        error_message: 合规检查的错误信息
        original_prompt: 原始问题提示词
        
    Returns:
        RETHINK 提示词
    """
    prompt = f"""Your previous code failed the **Dual-Task Compliance Check**.

**Error:** {error_message}

**Correction Strategy:**

1. **Keep** the Helper Function `{helper_name}` logic (it is likely correct).
2. **Delete** the internal logic inside `{main_name}` that duplicates the Helper's functionality.
3. **Replace** it with a loop or map that explicitly calls `{helper_name}(...)`.

**Your Previous Code:**

```python
{code}
```

**Original Task:**

{original_prompt}

**Output:** Provide the FULL corrected Python code. Ensure that `{main_name}` explicitly calls `{helper_name}` at least once.
"""
    return prompt


def check_and_validate_dual_task(
    code: str,
    helper_name: str,
    main_name: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    检查代码是否符合双任务要求，如果不符合，生成 RETHINK 提示词。
    
    Args:
        code: 生成的代码
        helper_name: 辅助函数名称
        main_name: 主函数名称
        
    Returns:
        (is_compliant, error_message, rethink_prompt)
        - is_compliant: True 如果符合要求
        - error_message: 错误信息（如果不符合）
        - rethink_prompt: RETHINK 提示词（如果不符合，用于重新生成）
    """
    is_compliant, error_message = check_dual_task_compliance(
        code, helper_name, main_name
    )
    
    if is_compliant:
        return True, None, None
    else:
        # 生成 RETHINK 提示词（需要原始 prompt，这里先返回基础版本）
        rethink_prompt = f"""Your previous code failed the **Dual-Task Compliance Check**.

**Error:** {error_message}

**Correction Strategy:**

1. **Keep** the Helper Function `{helper_name}` logic (it is likely correct).
2. **Delete** the internal logic inside `{main_name}` that duplicates the Helper's functionality.
3. **Replace** it with a loop or map that explicitly calls `{helper_name}(...)`.

**Your Previous Code:**

```python
{code}
```

**Output:** Provide the FULL corrected Python code. Ensure that `{main_name}` explicitly calls `{helper_name}` at least once.
"""
        return False, error_message, rethink_prompt


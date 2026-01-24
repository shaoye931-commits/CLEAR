from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any


class SandboxResult:
    def __init__(
        self,
        success: bool,
        stdout: str,
        stderr: str,
        exit_code: int,
        execution_trace: Optional[List[Dict[str, Any]]] = None,
    ):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.execution_trace = execution_trace or []


def _ensure_docker_available() -> Optional[str]:
    try:
        subprocess.run(["docker", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return None
    except Exception as e:  # noqa: BLE001
        return f"Docker not available: {e}"


def build_traced_test_script(
    tests: str,
    helper_name: Optional[str] = None,
) -> str:
    """
    构建带执行追踪的测试脚本。
    追踪辅助函数的调用记录（输入和输出）。
    
    Args:
        tests: 原始测试脚本
        helper_name: 辅助函数名，如果提供则启用追踪
    
    Returns:
        带追踪功能的测试脚本
    """
    if not helper_name:
        return tests
    
    # 创建追踪包装器
    trace_code = f"""
import json
import sys
from solution import *

# 追踪列表（存储所有调用记录）
_execution_trace = []

# 尝试获取并包装辅助函数
try:
    # 获取原始辅助函数
    _original_helper = getattr(solution, '{helper_name}', None)
    
    if _original_helper is None:
        # 辅助函数不存在，记录错误但不中断执行
        _execution_trace.append({{
            "error": "Helper function '{helper_name}' not found in solution module"
        }})
    else:
        # 定义包装函数以追踪调用
        def _traced_helper(*args, **kwargs):
            try:
                # 调用原函数
                result = _original_helper(*args, **kwargs)
                
                # 记录调用信息
                _execution_trace.append({{
                    "input": {{"args": list(args), "kwargs": kwargs}},
                    "output": result,
                    "error": None
                }})
                
                return result
            except Exception as e:
                # 记录调用时的错误
                _execution_trace.append({{
                    "input": {{"args": list(args), "kwargs": kwargs}},
                    "output": None,
                    "error": str(e)
                }})
                raise
        
        # 替换原函数
        setattr(solution, '{helper_name}', _traced_helper)
except Exception as e:
    # 包装过程出错，记录但不中断
    _execution_trace.append({{
        "error": f"Failed to wrap helper function: {{str(e)}}"
    }})

# 执行测试（无论追踪是否成功都继续）
"""
    
    trace_code += tests
    
    # 在测试后输出追踪信息（无论成功失败都输出）
    trace_code += f"""
# 输出追踪信息（JSON格式）
try:
    print("<<TRACE_START>>")
    print(json.dumps(_execution_trace, indent=2, default=str))
    print("<<TRACE_END>>")
except Exception:
    # 如果序列化失败，至少输出标记
    print("<<TRACE_START>>")
    print(json.dumps([{{"error": "Failed to serialize trace"}}], indent=2))
    print("<<TRACE_END>>")
"""
    
    return trace_code


def run_in_sandbox(
    code: str,
    tests: str,
    *,
    image: str = "tdir-sandbox:latest",
    time_limit_s: int = 10,
    memory: str = "512m",
    cpus: str = "1.0",
    helper_name: Optional[str] = None,
) -> SandboxResult:
    """
    Execute provided code and tests inside a Docker container with strict limits.
    Returns SandboxResult with captured stdout/stderr and exit code.
    """
    docker_err = _ensure_docker_available()

    temp_dir = Path(tempfile.mkdtemp(prefix="tdir_sbx_"))
    try:
        code_path = temp_dir / "solution.py"
        test_path = temp_dir / "run_tests.py"

        code_path.write_text(code, encoding="utf-8")
        
        # 如果指定了辅助函数名，构建带追踪的测试脚本
        if helper_name:
            traced_tests = build_traced_test_script(tests, helper_name)
            test_path.write_text(traced_tests, encoding="utf-8")
        else:
            test_path.write_text(tests, encoding="utf-8")

        if not docker_err:
            # Build docker image if not exists (best-effort)
            # Users should pre-build with: docker build -t tdir-sandbox docker/
            cmd = [
                "docker",
                "run",
                "--rm",
                "--network", "none",
                "--cpus", cpus,
                "--memory", memory,
                "--pids-limit", "256",
                "--ulimit", "nofile=256:256",
                "--read-only",
                "-v", f"{str(temp_dir)}:/workspace:rw",
                "-w", "/workspace",
                image,
                "bash",
                "-lc",
                f"python -m py_compile solution.py && timeout {time_limit_s}s python run_tests.py",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            success = proc.returncode == 0
            
            # 解析执行追踪
            execution_trace = []
            if helper_name:
                trace_start = "<<TRACE_START>>"
                trace_end = "<<TRACE_END>>"
                if trace_start in proc.stdout and trace_end in proc.stdout:
                    # 使用正则表达式提取标记之间的内容
                    pattern = re.compile(
                        re.escape(trace_start) + r"(.*?)" + re.escape(trace_end),
                        re.DOTALL
                    )
                    match = pattern.search(proc.stdout)
                    if match:
                        trace_text = match.group(1).strip()
                        try:
                            execution_trace = json.loads(trace_text)
                            if not isinstance(execution_trace, list):
                                execution_trace = []
                        except json.JSONDecodeError:
                            execution_trace = []
            
            return SandboxResult(
                success, proc.stdout, proc.stderr, proc.returncode, execution_trace
            )

        # Fallback: run locally without Docker (no isolation). Time-limited via subprocess timeout.
        try:
            compile_proc = subprocess.run(
                [sys.executable, "-m", "py_compile", str(code_path)],
                cwd=str(temp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=time_limit_s,
            )
            if compile_proc.returncode != 0:
                return SandboxResult(False, compile_proc.stdout, compile_proc.stderr, compile_proc.returncode)

            run_proc = subprocess.run(
                [sys.executable, str(test_path)],
                cwd=str(temp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=time_limit_s,
            )
            
            # 解析执行追踪（本地执行）
            execution_trace = []
            if helper_name:
                trace_start = "<<TRACE_START>>"
                trace_end = "<<TRACE_END>>"
                if trace_start in run_proc.stdout and trace_end in run_proc.stdout:
                    # 使用正则表达式提取标记之间的内容
                    pattern = re.compile(
                        re.escape(trace_start) + r"(.*?)" + re.escape(trace_end),
                        re.DOTALL
                    )
                    match = pattern.search(run_proc.stdout)
                    if match:
                        trace_text = match.group(1).strip()
                        try:
                            execution_trace = json.loads(trace_text)
                            if not isinstance(execution_trace, list):
                                execution_trace = []
                        except json.JSONDecodeError:
                            execution_trace = []
            
            return SandboxResult(
                run_proc.returncode == 0,
                run_proc.stdout,
                run_proc.stderr,
                run_proc.returncode,
                execution_trace,
            )
        except subprocess.TimeoutExpired as te:
            return SandboxResult(False, te.stdout or "", (te.stderr or "") + "\nTIMEOUT", exit_code=124)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def default_test_wrapper(function_name: str, tests_body: str) -> str:
    """
    Compose a test runner that imports solution and executes test assertions.
    tests_body should contain plain python assertions calling the function.
    """
    return (
        "import solution\n"
        f"fn = getattr(solution, '{function_name}', None)\n"
        "assert callable(fn), 'Expected a callable named " + repr('" + function_name + "') + "'\n"
        + tests_body
        + "\nprint('ALL_TESTS_PASSED')\n"
    )



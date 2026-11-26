from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

class DockerUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int


@dataclass(frozen=True)
class DockerArtifactResult:
    execution: SandboxResult
    artifact: str | None


def load_original_environment() -> None:
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("'\""))


def extract_code(response_text: str, *, use_cot: bool = False) -> tuple[str, str]:
    match = re.search(r"```(?:python)?\s*(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip(), "fenced_code"
    return response_text.strip(), "plain_text"


def docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def docker_image_available(image: str = "clear-sandbox:latest") -> bool:
    if not docker_available():
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _validate_artifact_name(artifact_name: str | None) -> None:
    if artifact_name is None:
        return
    if not artifact_name or Path(artifact_name).name != artifact_name:
        raise ValueError("artifact_name must be a plain file name")


_CONTAINER_BOOTSTRAP = r"""
import json
import pathlib
import subprocess
import sys

request = json.load(sys.stdin)
workspace = pathlib.Path("/workspace")
(workspace / "solution.py").write_text(request["code"], encoding="utf-8")
(workspace / "run_tests.py").write_text(request["tests"], encoding="utf-8")
compile_run = subprocess.run(
    ["python", "-m", "py_compile", "solution.py"],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
)
if compile_run.returncode == 0:
    test_run = subprocess.run(
        ["timeout", f'{request["time_limit_s"]}s', "python", "run_tests.py"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    exit_code = test_run.returncode
    stdout = compile_run.stdout + test_run.stdout
    stderr = compile_run.stderr + test_run.stderr
else:
    exit_code = compile_run.returncode
    stdout = compile_run.stdout
    stderr = compile_run.stderr
artifact = None
if request["artifact_name"]:
    artifact_path = workspace / request["artifact_name"]
    if artifact_path.is_file():
        artifact = artifact_path.read_text(encoding="utf-8", errors="replace")
json.dump(
    {"exit_code": exit_code, "stdout": stdout, "stderr": stderr, "artifact": artifact},
    sys.stdout,
)
"""


def _run_untrusted_python(
    code: str,
    tests: str,
    *,
    artifact_name: str | None,
    image: str,
    time_limit_s: int,
    memory: str,
    cpus: str,
) -> DockerArtifactResult:
    if time_limit_s <= 0:
        raise ValueError("time_limit_s must be positive")
    _validate_artifact_name(artifact_name)
    if not docker_available():
        raise DockerUnavailableError("Docker is required for untrusted code execution")

    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--cpus",
        cpus,
        "--memory",
        memory,
        "--memory-swap",
        memory,
        "--pids-limit",
        "256",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--ulimit",
        "nofile=256:256",
        "--read-only",
        "--tmpfs",
        "/workspace:rw,exec,nosuid,nodev,size=64m,mode=1777",
        "-w",
        "/workspace",
        image,
        "python",
        "-c",
        _CONTAINER_BOOTSTRAP,
    ]
    request = json.dumps(
        {
            "code": code,
            "tests": tests,
            "artifact_name": artifact_name,
            "time_limit_s": time_limit_s,
        }
    )
    try:
        result = subprocess.run(
            command,
            input=request,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=time_limit_s + 15,
        )
    except subprocess.TimeoutExpired as error:
        execution = SandboxResult(
            success=False,
            stdout=error.stdout or "",
            stderr=(error.stderr or "") + "\nDocker command timed out",
            exit_code=125,
        )
        return DockerArtifactResult(execution=execution, artifact=None)
    if result.returncode != 0:
        execution = SandboxResult(False, result.stdout, result.stderr, result.returncode)
        return DockerArtifactResult(execution=execution, artifact=None)
    try:
        payload = json.loads(result.stdout)
        exit_code = int(payload["exit_code"])
        stdout = str(payload["stdout"])
        stderr = str(payload["stderr"])
        artifact = payload.get("artifact")
        if artifact is not None and not isinstance(artifact, str):
            raise TypeError("artifact is not text")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        execution = SandboxResult(
            False,
            "",
            f"Invalid Docker execution response: {error}; docker stderr: {result.stderr}",
            125,
        )
        return DockerArtifactResult(execution=execution, artifact=None)
    execution = SandboxResult(exit_code == 0, stdout, stderr, exit_code)
    return DockerArtifactResult(execution=execution, artifact=artifact)


def run_untrusted_python(
    code: str,
    tests: str,
    *,
    image: str = "clear-sandbox:latest",
    time_limit_s: int = 3,
    memory: str = "512m",
    cpus: str = "1.0",
) -> SandboxResult:
    """Execute only through Docker; never fall back to the host interpreter."""
    return _run_untrusted_python(
        code,
        tests,
        artifact_name=None,
        image=image,
        time_limit_s=time_limit_s,
        memory=memory,
        cpus=cpus,
    ).execution


def run_untrusted_python_with_artifact(
    code: str,
    tests: str,
    *,
    artifact_name: str,
    image: str = "clear-sandbox:latest",
    time_limit_s: int = 3,
    memory: str = "512m",
    cpus: str = "1.0",
) -> DockerArtifactResult:
    """Docker-only execution with one artifact returned from an isolated tmpfs workspace."""
    return _run_untrusted_python(
        code,
        tests,
        artifact_name=artifact_name,
        image=image,
        time_limit_s=time_limit_s,
        memory=memory,
        cpus=cpus,
    )

from __future__ import annotations

import ast
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_IMPORTS: Set[str] = {
    "pandas",
    "numpy",
    "scipy",
    "sklearn",
    "math",
    "statistics",
    "json",
    "re",
    "datetime",
    "collections",
}

BLOCKED_BUILTINS: Set[str] = {
    "open",
    "eval",
    "exec",
    "__import__",
    "compile",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)


@dataclass
class PythonResult:
    success: bool
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    code_executed: str = ""
    execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "outputs": self.outputs,
            "error": self.error,
            "code_executed": self.code_executed,
            "execution_time": self.execution_time,
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_code(code: str) -> ValidationResult:
    """
    Static AST check for blocked imports and builtins.
    Returns ValidationResult with errors if any violations found.
    """
    errors: List[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return ValidationResult(valid=False, errors=[f"SyntaxError: {e}"])

    for node in ast.walk(tree):
        # Check import statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_module = alias.name.split(".")[0]
                if top_module not in ALLOWED_IMPORTS:
                    errors.append(f"Blocked import: '{alias.name}'")

        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module not in ALLOWED_IMPORTS:
                errors.append(f"Blocked import from: '{node.module}'")

        # Check for blocked builtin calls
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BLOCKED_BUILTINS:
                errors.append(f"Blocked builtin: '{func.id}'")
            elif isinstance(func, ast.Attribute) and func.attr in BLOCKED_BUILTINS:
                errors.append(f"Blocked attribute call: '{func.attr}'")

        # Check for __dunder__ attribute access that could escape sandbox
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__") and node.attr not in (
                "__init__",
                "__str__",
                "__repr__",
                "__len__",
                "__iter__",
                "__next__",
                "__class__",
            ):
                errors.append(f"Blocked dunder attribute access: '{node.attr}'")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

_RUNNER_TEMPLATE = textwrap.dedent(
    """
import sys
import json
import pandas as pd
import numpy as np

PARQUET_PATH = {parquet_path!r}

# Load data (read-only)
df = pd.read_parquet(PARQUET_PATH)

# ---- User code ----
{user_code}
# ---- End user code ----

# Capture result
_result = locals().get("result", None)
if isinstance(_result, pd.DataFrame):
    print(json.dumps({{"type": "dataframe", "data": _result.to_dict(orient="records")}}))
elif _result is not None:
    try:
        print(json.dumps({{"type": "value", "data": _result}}))
    except TypeError:
        print(json.dumps({{"type": "value", "data": str(_result)}}))
"""
)


def execute_python(
    code: str,
    parquet_path: str,
    timeout_seconds: int = 30,
) -> PythonResult:
    """
    Execute *code* in a sandboxed subprocess.
    - Data is provided via read-only parquet path.
    - Network access is not disabled at OS level here, but no network imports are allowed.
    - Timeout enforced via subprocess timeout.
    """
    validation = validate_code(code)
    if not validation.valid:
        return PythonResult(
            success=False,
            error="Code validation failed:\n" + "\n".join(validation.errors),
            code_executed=code,
        )

    runner_code = _RUNNER_TEMPLATE.format(
        parquet_path=parquet_path,
        user_code=textwrap.indent(code, "    "),
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(runner_code)
        tmp_path = tmp.name

    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "")},
        )
        elapsed = time.monotonic() - start

        if proc.returncode != 0:
            return PythonResult(
                success=False,
                error=proc.stderr.strip(),
                code_executed=code,
                execution_time=elapsed,
            )

        import json

        outputs: Dict[str, Any] = {}
        stdout = proc.stdout.strip()
        if stdout:
            try:
                outputs = json.loads(stdout)
            except json.JSONDecodeError:
                outputs = {"stdout": stdout}

        return PythonResult(
            success=True,
            outputs=outputs,
            code_executed=code,
            execution_time=elapsed,
        )

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return PythonResult(
            success=False,
            error=f"Execution timed out after {timeout_seconds}s",
            code_executed=code,
            execution_time=elapsed,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

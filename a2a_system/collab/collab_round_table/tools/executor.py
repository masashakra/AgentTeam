"""
executor.py — Python code execution tool (NOT an agent).
Used directly by CoderAgentRT and DebuggerAgent via import.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time


def run_python(code: str, timeout: int = 10) -> dict:
    """
    Run Python code in a subprocess.

    Returns:
        {
          "stdout": str,
          "stderr": str,
          "success": bool,
          "runtime_ms": float
        }
    """
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp_path = f.name

    start = time.perf_counter()
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        runtime_ms = (time.perf_counter() - start) * 1000
        return {
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:2000],
            "success": result.returncode == 0,
            "runtime_ms": round(runtime_ms, 2),
        }
    except subprocess.TimeoutExpired:
        runtime_ms = (time.perf_counter() - start) * 1000
        return {
            "stdout": "",
            "stderr": f"TimeoutExpired: code did not complete within {timeout}s",
            "success": False,
            "runtime_ms": round(runtime_ms, 2),
        }
    except Exception as exc:
        runtime_ms = (time.perf_counter() - start) * 1000
        return {
            "stdout": "",
            "stderr": str(exc),
            "success": False,
            "runtime_ms": round(runtime_ms, 2),
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

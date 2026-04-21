"""
CodeValidatorAgent — port 8005
Called on final code output only. Runs pylint + radon, then generates a
structured validation report via think→act pattern. Stateless.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import uvicorn

from groq_setup.infer import groq_complete

from shared.base_agent import BaseAgent
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact,
    Message, extract_text, extract_data, text_artifact,
)

CARD = AgentCard(
    name="Code Validator Agent",
    description="Runs pylint + radon on final code and produces a structured validation report.",
    url="http://localhost:8005",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
    skills=[AgentSkill(
        id="validate",
        name="validate",
        description="Static analysis and complexity validation of Python code.",
        inputModes=["data"],
        outputModes=["text"],
    )],
)

SYSTEM = """\
You are a senior Python code reviewer specializing in static analysis.
You evaluate code for correctness, style, and complexity."""

THINK_SUFFIX = """

Before writing your report, analyze:
Does the code have syntax errors? What is the cyclomatic complexity?
Are there style violations? Output 3-5 bullet points. Do NOT write the report yet."""

ACT_PROMPT = (
    "Good. Now write your validation report as JSON with these fields: "
    "pylint_score (0-10, float), complexity (\"low\"/\"medium\"/\"high\"), "
    "issues (list of strings), suggestions (list of strings), executable (bool). "
    "Raw JSON only, no markdown."
)


def _run_pylint(code: str) -> tuple[float, str]:
    """Run pylint and return (score, raw_output). Score is 0-10."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pylint", tmp,
             "--output-format=text", "--score=yes",
             "--disable=C0114,C0115,C0116"],  # disable missing-docstring
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        score = 0.0
        for line in output.splitlines():
            if "rated at" in line:
                m = re.search(r"([\-\d.]+)/10", line)
                if m:
                    try:
                        score = max(0.0, float(m.group(1)))
                    except ValueError:
                        pass
        return round(score, 2), output[:800]
    except FileNotFoundError:
        return 0.0, "pylint not found"
    except subprocess.TimeoutExpired:
        return 0.0, "pylint timed out"
    except Exception as exc:
        return 0.0, str(exc)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _run_radon(code: str) -> tuple[str, str]:
    """Run radon cc and return (complexity_level, raw_output)."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, "-m", "radon", "cc", tmp, "-s", "-a"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        # Parse average complexity from output
        level = "low"
        for line in output.splitlines():
            if "Average complexity" in line:
                m = re.search(r"\(([A-F])\)", line)
                if m:
                    grade = m.group(1)
                    level = "low" if grade in ("A", "B") else "medium" if grade == "C" else "high"
        return level, output[:400]
    except FileNotFoundError:
        return "unknown", "radon not found"
    except subprocess.TimeoutExpired:
        return "unknown", "radon timed out"
    except Exception as exc:
        return "unknown", str(exc)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


class CodeValidatorAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        data = extract_data(message)
        code = data.get("code", extract_text(message))
        task = data.get("task", "")

        # Run static analysis tools
        pylint_score, pylint_output = await asyncio.to_thread(_run_pylint, code)
        complexity_level, radon_output = await asyncio.to_thread(_run_radon, code)

        analysis_context = (
            f"Task: {task}\n\n"
            f"Code to validate:\n{code[:1500]}\n\n"
            f"Pylint score: {pylint_score}/10\n"
            f"Pylint output:\n{pylint_output}\n\n"
            f"Radon complexity: {complexity_level}\n"
            f"Radon output:\n{radon_output}"
        )

        # ── Turn 1: Think ──────────────────────────────────────────────────────
        thinking = await asyncio.to_thread(
            groq_complete,
            [{"role": "user", "content": analysis_context + THINK_SUFFIX}],
            SYSTEM,
            1024,
        )

        # ── Turn 2: Act ────────────────────────────────────────────────────────
        report_raw = await asyncio.to_thread(
            groq_complete,
            [
                {"role": "user",      "content": analysis_context + THINK_SUFFIX},
                {"role": "assistant", "content": thinking},
                {"role": "user",      "content": ACT_PROMPT},
            ],
            SYSTEM,
            1024,
        )

        # Strip markdown fences
        stripped = report_raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            stripped = "\n".join(inner).strip()

        # Parse and inject real scores
        try:
            report = json.loads(stripped)
        except json.JSONDecodeError:
            report = {
                "pylint_score": pylint_score,
                "complexity": complexity_level,
                "issues": [],
                "suggestions": [],
                "executable": False,
            }

        # Always use real pylint/radon scores
        report["pylint_score"] = pylint_score
        report["complexity"] = complexity_level

        return [text_artifact("validation_result", json.dumps(report, indent=2))]


agent = CodeValidatorAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.code_validator_agent:app", host="0.0.0.0", port=8005, reload=False)

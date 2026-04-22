"""
Debugger Agent — port 8008
Dynamic code debugging: executes code against test suite, identifies issues, reports findings.
Part of the Boss-Worker pipeline: Boss → Planner → Coder → Debugger → Reviewer
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import uvicorn

from groq_setup.infer import groq_chat, get_tool_call, tool_result_message

from shared.base_agent import BaseAgent
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact,
    DataPart, Message, extract_data, extract_text, text_artifact,
)

MAX_TOOL_CALLS = 6


def _exec_python(code: str, timeout: int = 10) -> dict:
    """Execute Python code and return structured results."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stderr": f"Timeout after {timeout}s"}
    except Exception as exc:
        return {"success": False, "stderr": str(exc)}
    finally:
        os.unlink(tmp_path)

CARD = AgentCard(
    name="Debugger Agent",
    description="Debug Python code by running tests and identifying issues.",
    url="http://localhost:8008",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
    skills=[AgentSkill(
        id="debug",
        name="debug",
        description="Debug Python code: run tests, identify issues, suggest fixes.",
        inputModes=["text", "data"],
        outputModes=["text"],
    )],
)

SYSTEM = """\
You are a Python debugging specialist. Your job is to:
1. Analyze the provided code carefully
2. Run the code against the provided test suite
3. Capture any errors, failures, or edge cases
4. Generate a structured debug report with findings and suggestions
5. Be concise but thorough

Focus on:
- Runtime errors and exceptions
- Test failures (which tests fail, why)
- Edge cases that might break the code
- Specific line numbers where issues occur
- Concrete suggestions to fix the issues

Output your findings as a structured report."""

DEBUG_TOOLS = [
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Execute Python code and capture output.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
            },
            "required": ["code"],
        },
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Submit final debug report.",
        "parameters": {
            "type": "object",
            "properties": {
                "report": {"type": "string", "description": "Final debug report"},
            },
            "required": ["report"],
        },
    }},
]


class DebuggerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        code = extract_text(message)
        data = extract_data(message)
        test_suite = data.get("test_suite", [])

        messages = [
            {
                "role": "user",
                "content": f"""Debug this Python code:

```python
{code}
```

Test Suite (run each test):
{self._format_tests(test_suite)}

Run the tests and provide a debug report.""",
            }
        ]
        last_report = ""

        async with asyncio.timeout(30):
            for _ in range(MAX_TOOL_CALLS):
                assistant_msg = await asyncio.to_thread(
                    groq_chat, messages, DEBUG_TOOLS, SYSTEM, "required", 1024
                )
                messages.append(assistant_msg)

                tc = get_tool_call(assistant_msg)
                if tc is None:
                    break
                name, args, call_id = tc

                if name == "finish":
                    last_report = args.get("report", "")
                    messages.append(tool_result_message(call_id, "Report submitted."))
                    break

                elif name == "run_python":
                    exec_code = args.get("code", "")
                    try:
                        result = await asyncio.to_thread(_exec_python, exec_code)
                        tool_result = json.dumps(result)
                    except Exception as e:
                        tool_result = json.dumps({"success": False, "stderr": str(e)})
                    messages.append(tool_result_message(call_id, tool_result))

                else:
                    messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

        return [text_artifact("debug_report", last_report or "No debug report generated.")]

    def _format_tests(self, test_suite: list[dict]) -> str:
        if not test_suite:
            return "(No tests provided)"
        tests_str = ""
        for i, test in enumerate(test_suite, 1):
            tests_str += f"\nTest {i}: {test.get('description', 'test')}\n"
            tests_str += f"  Input: {test.get('input', 'N/A')}\n"
            tests_str += f"  Expected: {test.get('expected', 'N/A')}\n"
        return tests_str


agent = DebuggerAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.debugger_agent:app", host="0.0.0.0", port=8008, reload=False)

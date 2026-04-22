"""
Debugger Agent — port 8008
Executes code and catches runtime errors (exceptions, crashes, output issues).
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
2. Run the code and capture any errors or exceptions
3. Report what works and what breaks
4. Generate a structured debug report with findings

Focus on:
- Runtime errors and exceptions
- Crashes or unexpected behavior
- Output verification
- Specific issues and how to fix them

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

        messages = [
            {
                "role": "user",
                "content": f"""Run this Python code and report any errors:

```python
{code}
```

Execute the code, capture any runtime errors or exceptions, and provide a debug report.""",
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


agent = DebuggerAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.debugger_agent:app", host="0.0.0.0", port=8008, reload=False)

"""
Debugger Agent — port 8008
Executes code, catches runtime errors, and attempts to fix them.
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
    description="Debug Python code by running it, catching errors, and fixing them.",
    url="http://localhost:8008",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
    skills=[AgentSkill(
        id="debug",
        name="debug",
        description="Debug and fix Python code: run, identify errors, fix them.",
        inputModes=["text"],
        outputModes=["text"],
    )],
)

SYSTEM = """\
You are a Python debugging specialist. Your job is to:
1. Analyze the provided code carefully
2. Run the code and identify any errors or exceptions
3. Fix the errors by modifying the code
4. Test your fixes by running the code again
5. Return the fixed code or a detailed debug report if unfixable

Workflow:
1. Try to run the code — if it works, report success
2. If there are errors, analyze and propose fixes
3. Use run_python to test your proposed fixes
4. Iterate until the code works
5. Return the final fixed code via finish()

Be systematic and thorough. Try multiple approaches if needed."""

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
        "description": "Return fixed code or debug analysis if unfixable.",
        "parameters": {
            "type": "object",
            "properties": {
                "fixed_code": {"type": "string", "description": "Fixed code if successful, or debug analysis if unfixable"},
            },
            "required": ["fixed_code"],
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
                "content": f"""Debug and fix this Python code:

```python
{code}
```

Execute the code. If there are errors, fix them and test the fixes. Return the fixed code.""",
            }
        ]
        last_result = ""

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
                    last_result = args.get("fixed_code", "")
                    messages.append(tool_result_message(call_id, "Fixed code submitted."))
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

        return [text_artifact("fixed_code", last_result or "No fixed code generated.")]


agent = DebuggerAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.debugger_agent:app", host="0.0.0.0", port=8008, reload=False)

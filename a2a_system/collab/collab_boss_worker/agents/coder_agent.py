"""
Coder Agent — port 8002
True agent: writes code, runs it with run_python, self-corrects, returns when satisfied.
Uses Groq (llama-3.3-70b-versatile) via groq_setup.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import uvicorn

from groq_setup.infer import groq_chat, groq_complete, get_tool_call, tool_result_message

from shared.base_agent import BaseAgent
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact,
    Message, extract_data, extract_text, text_artifact,
)

MAX_TOOL_CALLS = 10

CARD = AgentCard(
    name="Coder Agent",
    description="True agent: writes Python code, runs it, self-corrects, returns only when it works.",
    url="http://localhost:8002",
    version="3.0.0",
    capabilities=AgentCapabilities(streaming=True),
    skills=[AgentSkill(
        id="code", name="code",
        description="Implement and self-test Python code given a technical plan.",
        inputModes=["text", "data"], outputModes=["text"],
    )],
)

SYSTEM = """\
You are an expert Python developer. Implement Python code based on the technical plan.

You can run code with run_python(code) to test it. When done, call finish(code) with your final implementation.

Guidelines:
- Write clean, working code with type hints and docstrings
- Test your code with run_python to verify it works
- Fix any errors and retry until it passes
- Use only standard Python 3.12 typing (no typing_extensions)
- No markdown fences in final code
"""

CODER_TOOLS = [
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Execute Python code and return stdout and stderr.",
        "parameters": {"type": "object",
            "properties": {"code": {"type": "string", "description": "Python code to execute"}},
            "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Return the final implementation when satisfied it is correct.",
        "parameters": {"type": "object",
            "properties": {"code": {"type": "string", "description": "The final clean implementation"}},
            "required": ["code"]},
    }},
]


def _run_python(code: str, timeout: int = 10) -> str:
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=timeout,
        )
        out = ""
        if result.stdout:
            out += f"STDOUT:\n{result.stdout}"
        if result.stderr:
            out += f"STDERR:\n{result.stderr}"
        output = out or "(no output)"
        return output[:2000] + ("\n...(truncated)" if len(output) > 2000 else "")
    except subprocess.TimeoutExpired:
        return f"ERROR: timed out after {timeout}s"
    except Exception as exc:
        return f"ERROR: {exc}"
    finally:
        os.unlink(tmp_path)


class CoderAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        plan = extract_text(message)
        data = extract_data(message)
        feedback = data.get("feedback", "")

        user_content = f"Technical plan:\n{plan}"
        if feedback:
            user_content += f"\n\nReviewer feedback to address:\n{feedback}"

        messages = [{"role": "user", "content": user_content}]
        last_code = ""

        for step in range(MAX_TOOL_CALLS):
            assistant_msg = await asyncio.to_thread(
                groq_chat, messages, CODER_TOOLS, SYSTEM, "auto", 2048
            )
            messages.append(assistant_msg)

            tc = get_tool_call(assistant_msg)
            if tc is None:
                break
            name, args, call_id = tc

            if name == "finish":
                last_code = args.get("code", last_code)
                return [text_artifact("implementation", last_code)]

            elif name == "run_python":
                code = args["code"]
                last_code = code
                result = _run_python(code)
                print(f"[CoderAgent] run_python step {step+1} → {result[:60].strip()}...")
                messages.append(tool_result_message(call_id, result))

            else:
                messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

        if not last_code:
            raise RuntimeError("Coder loop ended without producing code.")
        return [text_artifact("implementation", last_code)]


agent = CoderAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.coder_agent:app", host="0.0.0.0", port=8002, reload=False)

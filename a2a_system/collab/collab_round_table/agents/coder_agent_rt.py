"""
CoderAgentRT — port 8011
Round Table Coder: writes, runs, and iterates on implementation code.
Calls executor.run_python directly. Shares execution results with peers.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import httpx
import uvicorn

from groq_setup.infer import groq_chat, get_tool_call, tool_result_message

from shared.base_agent import BaseAgent, _auth_headers
from shared.discover import find_agent_by_name
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact,
    DataPart, Message, TaskSendParams, extract_data, extract_text, text_artifact,
)
from tools.executor import run_python as _exec_python

MAX_TOOL_CALLS = 6
AGENT_PORT = int(os.getenv("CODER_RT_PORT", "8011"))
AGENT_HOST = os.getenv("AGENT_HOST", "localhost")
AGENT_URL = os.getenv("CODER_RT_URL", f"http://{AGENT_HOST}:{AGENT_PORT}")

# Short peer name → registered agent name in the registry
PEER_NAMES: dict[str, str] = {
    "Architect": "Architect Agent",
    "Debugger":  "Debugger Agent",
    "Tester":    "Tester Agent",
}

CARD = AgentCard(
    name="Coder Agent RT",
    description="Python developer in the Round Table: writes and tests implementation code.",
    url=AGENT_URL,
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
    skills=[AgentSkill(
        id="collaborate",
        name="collaborate",
        description="Write and test Python implementation in peer-to-peer coding round.",
        inputModes=["data"],
        outputModes=["text"],
    )],
)

SYSTEM = """\
You are a Python developer in a peer-to-peer collaborative coding team.
Your role is to write and test implementation code. You are NOT the boss
— you are an equal peer. In each round you will receive messages from
your teammates (Architect, Debugger, Tester) and the current task.
You must: read all peer messages carefully, update your code based on
their feedback, use run_python to test your code and see real errors,
share execution results with peers via send_message, and finish with
your current best code. When you share execution results with peers,
include the actual stdout/stderr so they can help debug."""

CODER_RT_TOOLS = [
    {"type": "function", "function": {
        "name": "send_message",
        "description": "Send a message to a peer agent.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "enum": ["Architect", "Debugger", "Tester"],
                    "description": "Recipient agent name",
                },
                "content": {"type": "string", "description": "Message content"},
            },
            "required": ["to", "content"],
        },
    }},
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Execute Python code. Returns stdout, stderr, success flag, and runtime_ms.",
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
        "description": "Return your current best code implementation for this round.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Final code implementation"},
            },
            "required": ["code"],
        },
    }},
]


class CoderAgentRT(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)
        self._inbox: dict[int, list[dict]] = {}
        self._inbox_lock = asyncio.Lock()

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        data = extract_data(message)
        msg_type = data.get("type", "")

        # ── Peer message: store in inbox and return immediately ──────────────
        if msg_type == "peer_message":
            round_num = int(data.get("round", 0))
            async with self._inbox_lock:
                if round_num not in self._inbox:
                    self._inbox[round_num] = []
                self._inbox[round_num].append(data)
            return [text_artifact("peer_ack", "received")]

        # ── Orchestrator round: run full Groq loop ────────────────────────────
        task = data.get("task", extract_text(message))
        round_num = int(data.get("round", 1))
        max_rounds = int(data.get("max_rounds", 4))
        session_id = data.get("session_id", "")

        async with self._inbox_lock:
            inbox_msgs = list(self._inbox.get(round_num, []))
        last_inbox_idx = len(inbox_msgs)

        peer_context = ""
        if inbox_msgs:
            peer_context = "\n\nMessages from teammates:\n"
            for msg in inbox_msgs:
                peer_context += f"- {msg['sender']}: {msg['content']}\n"

        user_content = (
            f"Task: {task}\n"
            f"Round: {round_num}/{max_rounds}"
            f"{peer_context}"
        )

        messages = [{"role": "user", "content": user_content}]
        last_code = ""

        async with httpx.AsyncClient() as http:
            for _step in range(MAX_TOOL_CALLS):
                # Pull new inbox messages
                async with self._inbox_lock:
                    current_inbox = list(self._inbox.get(round_num, []))
                new_msgs = current_inbox[last_inbox_idx:]
                if new_msgs:
                    last_inbox_idx = len(current_inbox)
                    new_ctx = "\n[New teammate messages]\n"
                    for msg in new_msgs:
                        new_ctx += f"- {msg['sender']}: {msg['content']}\n"
                    messages.append({"role": "user", "content": new_ctx})

                assistant_msg = await asyncio.to_thread(
                    groq_chat, messages, CODER_RT_TOOLS, SYSTEM, "required", 4096
                )
                messages.append(assistant_msg)

                tc = get_tool_call(assistant_msg)
                if tc is None:
                    break
                name, args, call_id = tc

                if name == "finish":
                    last_code = args.get("code", last_code)
                    messages.append(tool_result_message(call_id, "Code submitted for this round."))
                    break

                elif name == "run_python":
                    code = args.get("code", "")
                    last_code = code
                    result = await asyncio.to_thread(_exec_python, code)
                    messages.append(tool_result_message(call_id, json.dumps(result)))

                elif name == "send_message":
                    to = args.get("to", "")
                    content = args.get("content", "")
                    peer_full_name = PEER_NAMES.get(to, "")
                    result_msg = f"Message sent to {to}."
                    if peer_full_name:
                        try:
                            peer_card = await find_agent_by_name(peer_full_name)
                            peer_params = TaskSendParams(
                                id=f"{task_id}-peer-{to.lower()}-{_step}",
                                message=Message(role="user", parts=[DataPart(data={
                                    "type": "peer_message",
                                    "round": round_num,
                                    "sender": "Coder",
                                    "content": content,
                                    "session_id": session_id,
                                })]),
                            )
                            await http.post(
                                f"{peer_card.url}/tasks/send",
                                json=peer_params.model_dump(mode="json"),
                                headers={**_auth_headers(), "X-Sender": "CoderAgentRT"},
                                timeout=10.0,
                            )
                        except Exception as exc:
                            result_msg = f"Failed to deliver to {to}: {exc}"
                        # Notify CommunicationLoggerAgent (best-effort)
                        try:
                            comm_card = await find_agent_by_name("Communication Logger Agent")
                            comm_params = TaskSendParams(
                                id=f"{task_id}-log-{_step}",
                                message=Message(role="user", parts=[DataPart(data={
                                    "type": "log_message",
                                    "session_id": session_id,
                                    "round": round_num,
                                    "sender": "Coder",
                                    "receiver": to,
                                    "content": content,
                                })]),
                            )
                            await http.post(
                                f"{comm_card.url}/tasks/send",
                                json=comm_params.model_dump(mode="json"),
                                headers={**_auth_headers(), "X-Sender": "CoderAgentRT"},
                                timeout=5.0,
                            )
                        except Exception:
                            pass
                    else:
                        result_msg = f"Unknown peer: {to}"
                    messages.append(tool_result_message(call_id, result_msg))

                else:
                    messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

        return [text_artifact("implementation", last_code or "# No implementation generated")]


agent = CoderAgentRT()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.coder_agent_rt:app", host="0.0.0.0", port=8011, reload=False)

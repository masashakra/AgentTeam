"""
ArchitectAgent — port 8010
Peer-to-peer Round Table: focuses on design, structure, and interfaces.
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
    DataPart, Message, Task, TaskSendParams, extract_data, extract_text, get_artifact_text, text_artifact,
)
from logger_rt import log_detailed_message

MAX_TOOL_CALLS = 6
AGENT_PORT = int(os.getenv("ARCHITECT_PORT", "8010"))
AGENT_HOST = os.getenv("AGENT_HOST", "localhost")
AGENT_URL = os.getenv("ARCHITECT_URL", f"http://{AGENT_HOST}:{AGENT_PORT}")

# Short peer name → registered agent name in the registry
PEER_NAMES: dict[str, str] = {
    "Coder":    "Coder Agent RT",
    "Debugger": "Debugger Agent",
    "Tester":   "Tester Agent",
}

CARD = AgentCard(
    name="Architect Agent",
    description="Software architect in the Round Table: focuses on design, structure, and interfaces.",
    url=AGENT_URL,
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
    skills=[AgentSkill(
        id="collaborate",
        name="collaborate",
        description="Participate in peer-to-peer collaborative coding round as architect.",
        inputModes=["data"],
        outputModes=["text"],
    )],
)

SYSTEM = """\
You are a software architect in a peer-to-peer collaborative coding team.
Your role is to think about design, structure, and interfaces.
You are NOT the boss — you are an equal peer. In each round you will
receive messages from your teammates (Coder, Debugger, Tester) and
the current task. You must: read all peer messages carefully, update
your design thinking based on their feedback, send specific helpful
messages to peers about design decisions, and finish with your current
design approach. Be specific and concrete. Ask questions when you need
clarification. Challenge ideas you disagree with."""

ARCH_TOOLS = [
    {"type": "function", "function": {
        "name": "send_message",
        "description": "Send a message to a peer agent in the round table.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "enum": ["Coder", "Debugger", "Tester"],
                    "description": "Recipient agent name",
                },
                "content": {
                    "type": "string",
                    "description": "Message content to send",
                },
            },
            "required": ["to", "content"],
        },
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Signal done for this round with your current design approach.",
        "parameters": {
            "type": "object",
            "properties": {
                "approach": {
                    "type": "string",
                    "description": "Your current design approach and decisions",
                },
            },
            "required": ["approach"],
        },
    }},
]


class ArchitectAgent(BaseAgent):
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

        # Snapshot inbox at start of round
        async with self._inbox_lock:
            inbox_msgs = list(self._inbox.get(round_num, []))
        last_inbox_idx = len(inbox_msgs)

        peer_context = ""
        if inbox_msgs:
            peer_context = "\n\nMessages from teammates this round:\n"
            for msg in inbox_msgs:
                peer_context += f"- {msg['sender']}: {msg['content']}\n"

        user_content = (
            f"Task: {task}\n"
            f"Round: {round_num}/{max_rounds}"
            f"{peer_context}"
        )

        messages = [{"role": "user", "content": user_content}]
        last_approach = ""

        async with httpx.AsyncClient() as http:
            for _step in range(MAX_TOOL_CALLS):
                # Pull any new inbox messages between Groq calls
                async with self._inbox_lock:
                    current_inbox = list(self._inbox.get(round_num, []))
                new_msgs = current_inbox[last_inbox_idx:]
                if new_msgs:
                    last_inbox_idx = len(current_inbox)
                    new_ctx = "\n[New messages from teammates]\n"
                    for msg in new_msgs:
                        new_ctx += f"- {msg['sender']}: {msg['content']}\n"
                    messages.append({"role": "user", "content": new_ctx})

                assistant_msg = await asyncio.to_thread(
                    groq_chat, messages, ARCH_TOOLS, SYSTEM, "required", 1024
                )
                messages.append(assistant_msg)

                tc = get_tool_call(assistant_msg)
                if tc is None:
                    break
                name, args, call_id = tc

                if name == "finish":
                    last_approach = args.get("approach", "")
                    messages.append(tool_result_message(call_id, "Round completed."))
                    break

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
                                    "sender": "Architect",
                                    "content": content,
                                    "session_id": session_id,
                                })]),
                            )
                            await http.post(
                                f"{peer_card.url}/tasks/send",
                                json=peer_params.model_dump(mode="json"),
                                headers={**_auth_headers(), "X-Sender": "ArchitectAgent"},
                                timeout=10.0,
                            )
                            # Log detailed message content
                            log_detailed_message(session_id, "Architect", to, round_num, content, "peer_message")
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
                                    "sender": "Architect",
                                    "receiver": to,
                                    "content": content,
                                })]),
                            )
                            await http.post(
                                f"{comm_card.url}/tasks/send",
                                json=comm_params.model_dump(mode="json"),
                                headers={**_auth_headers(), "X-Sender": "ArchitectAgent"},
                                timeout=5.0,
                            )
                        except Exception:
                            pass
                    else:
                        result_msg = f"Unknown peer: {to}"
                    messages.append(tool_result_message(call_id, result_msg))

                else:
                    messages.append(tool_result_message(call_id, f"Unknown tool: {name}"))

        worker_outputs = await self._run_peer_round(http, task_id, task, round_num, max_rounds, session_id)
        return [
            text_artifact("architect_approach", last_approach or "No approach finalized."),
            text_artifact("round_bundle", json.dumps(worker_outputs)),
        ]

    async def _run_peer_round(
        self,
        http: httpx.AsyncClient,
        task_id: str,
        task: str,
        round_num: int,
        max_rounds: int,
        session_id: str,
    ) -> dict[str, str]:
        peers = [
            ("Coder Agent RT", "Coder", "implementation"),
            ("Debugger Agent", "Debugger", "debugger_fix"),
            ("Tester Agent", "Tester", "test_feedback"),
        ]
        payload = {
            "type": "round_start",
            "task": task,
            "round": round_num,
            "max_rounds": max_rounds,
            "session_id": session_id,
        }
        outputs: dict[str, str] = {}

        async def _call_peer(peer_name: str, short_name: str, artifact_name: str) -> tuple[str, str]:
            try:
                peer_card = await find_agent_by_name(peer_name)
                params = TaskSendParams(
                    id=f"{task_id}-round-{short_name.lower()}",
                    sessionId=session_id,
                    message=Message(role="user", parts=[DataPart(data=payload)]),
                )
                resp = await http.post(
                    f"{peer_card.url}/tasks/send",
                    json=params.model_dump(mode="json"),
                    headers={**_auth_headers(), "X-Sender": "ArchitectAgent"},
                    timeout=300.0,
                )
                resp.raise_for_status()
                task_resp = Task.model_validate(resp.json())
                return short_name, get_artifact_text(task_resp, artifact_name)
            except Exception:
                return short_name, ""

        results = await asyncio.gather(
            *[_call_peer(peer_name, short_name, artifact_name) for peer_name, short_name, artifact_name in peers]
        )
        for short_name, output in results:
            outputs[short_name] = output
        return outputs


agent = ArchitectAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.architect_agent:app", host="0.0.0.0", port=8010, reload=False)

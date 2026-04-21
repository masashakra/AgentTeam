"""
CommunicationLoggerAgent — port 8016
Support agent (observational only). Records every A2A peer message.
Classifies message type using a single LLM call. Writes to JSONL.
Never sends A2A messages to worker agents.

Receives messages via standard A2A /tasks/send with DataPart type="log_message".
"""
from __future__ import annotations

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import uvicorn

from groq_setup.infer import groq_complete

from shared.base_agent import BaseAgent
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact,
    Message, extract_data, text_artifact,
)

from logger_rt import log_peer_message

AGENT_PORT = int(os.getenv("COMM_LOGGER_PORT", "8016"))
AGENT_HOST = os.getenv("AGENT_HOST", "localhost")
AGENT_URL = os.getenv("COMM_LOGGER_URL", f"http://{AGENT_HOST}:{AGENT_PORT}")

CARD = AgentCard(
    name="Communication Logger Agent",
    description="Records and classifies every peer message exchanged in the Round Table.",
    url=AGENT_URL,
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False, pushNotifications=False),
    skills=[AgentSkill(
        id="log",
        name="log",
        description="Log and classify a peer message.",
        inputModes=["data"],
        outputModes=["text"],
    )],
)

CLASSIFY_SYSTEM = (
    "Classify this message into exactly one type: "
    "question, suggestion, critique, defense, confirmation, rejection, update, instruction. "
    "Reply with just the type word, nothing else."
)

VALID_TYPES = frozenset({
    "question", "suggestion", "critique", "defense",
    "confirmation", "rejection", "update", "instruction",
})


async def _classify(content: str) -> str:
    """Return the message type via a single LLM call."""
    try:
        result = await asyncio.to_thread(
            groq_complete,
            [{"role": "user", "content": f"Message: {content[:500]}"}],
            CLASSIFY_SYSTEM,
            16,
        )
        label = result.strip().lower().split()[0] if result.strip() else "update"
        return label if label in VALID_TYPES else "update"
    except Exception:
        return "update"


class CommunicationLoggerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        data = extract_data(message)
        msg_type = data.get("type", "")

        # ── Log a peer message (sent via A2A tasks/send) ─────────────────────
        if msg_type == "log_message":
            session_id = data.get("session_id", "")
            sender = data.get("sender", "Unknown")
            receiver = data.get("receiver", "Unknown")
            round_num = int(data.get("round", 0))
            content = data.get("content", "")

            classified = await _classify(content)

            log_peer_message(
                session_id=session_id,
                sender=sender,
                receiver=receiver,
                round_num=round_num,
                message_type=classified,
                content=content,
            )
            return [text_artifact("comm_logger_ack", f"logged:{classified}")]

        # ── Status / unknown ──────────────────────────────────────────────────
        action = data.get("action", "status")
        if action == "status":
            return [text_artifact("comm_logger_status", "CommunicationLoggerAgent running.")]

        return [text_artifact("comm_logger_response", f"Unknown action: {action}")]


agent = CommunicationLoggerAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.comm_logger_agent:app", host="0.0.0.0", port=8016, reload=False)

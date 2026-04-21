"""
MetricsTrackerAgent — port 8017
Support agent (observational only). Tracks per-round metrics.
Writes to logs/round_table_metrics.jsonl. Never sends A2A messages to workers.

Receives metric events via standard A2A /tasks/send with DataPart containing
session_id, round, event, and data fields.
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent.parent.parent))

import uvicorn

from shared.base_agent import BaseAgent
from shared.models import (
    AgentCard, AgentCapabilities, AgentSkill, Artifact,
    Message, extract_data, text_artifact,
)

from a2a_system.collab.collab_boss_worker.logger_bw import log_metric

CARD = AgentCard(
    name="Metrics Tracker Agent",
    description="Tracks per-round metrics for the Round Table session.",
    url="http://localhost:8017",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False, pushNotifications=False),
    skills=[AgentSkill(
        id="track",
        name="track",
        description="Record a metric event for the current session.",
        inputModes=["data"],
        outputModes=["text"],
    )],
)

# Events: round_start, round_end, test_result, session_end, session_start


class MetricsTrackerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(CARD)

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:
        """Called by orchestrator for metric tracking or status queries."""
        data = extract_data(message)
        session_id = data.get("session_id", "")
        event = data.get("event", "")
        round_num = int(data.get("round", 0))
        event_data = data.get("data", {})

        if event:
            log_metric(session_id, round_num, event, event_data)
            return [text_artifact("metrics_ack", f"Logged event: {event}")]

        return [text_artifact("metrics_status", "MetricsTrackerAgent running.")]


agent = MetricsTrackerAgent()
app = agent.app

if __name__ == "__main__":
    uvicorn.run("agents.metrics_tracker_agent:app", host="0.0.0.0", port=8017, reload=False)

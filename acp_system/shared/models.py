"""
ACP (Agent Communication Protocol) Pydantic models.

Key concepts:
- Run       : the unit of work (like a task in A2A, or a tool call in MCP)
- Message   : a list of Parts sent to/from an agent
- Part      : one piece of a message — text, JSON, or binary data
- RunStatus : created → in_progress → completed | failed | cancelled
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Run status ────────────────────────────────────────────────────────────────

class RunStatus(str, Enum):
    created     = "created"
    in_progress = "in_progress"
    completed   = "completed"
    failed      = "failed"
    cancelled   = "cancelled"


# ── Message / Part ────────────────────────────────────────────────────────────

class MessagePart(BaseModel):
    """One piece of a message. content_type mirrors MIME types."""
    content:      str
    content_type: str        = "text/plain"   # or "application/json"
    name:         Optional[str] = None         # optional label for JSON parts


class Message(BaseModel):
    """A single message — one or more parts."""
    parts: list[MessagePart]


# ── Run ───────────────────────────────────────────────────────────────────────

class Run(BaseModel):
    """The core ACP object — represents one agent execution."""
    run_id:      str                    = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_name:  str
    status:      RunStatus              = RunStatus.created
    input:       list[Message]
    output:      Optional[list[Message]] = None
    error:       Optional[str]          = None
    created_at:  str                    = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: Optional[str]          = None


# ── Request / Response ────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    """Body of POST /runs or POST /runs/stream."""
    agent_name: str
    input:      list[Message]


class AgentCapabilities(BaseModel):
    streaming: bool = True


class AgentManifest(BaseModel):
    """Returned by GET /agents — describes what this agent can do."""
    name:         str
    description:  str
    version:      str
    capabilities: AgentCapabilities = AgentCapabilities()
    input_modes:  list[str] = ["text/plain", "application/json"]
    output_modes: list[str] = ["text/plain", "application/json"]


class AgentsResponse(BaseModel):
    agents: list[AgentManifest]


# ── SSE event models ──────────────────────────────────────────────────────────

class RunCreatedEvent(BaseModel):
    type:   str = "run.created"
    run_id: str
    agent_name: str

class RunInProgressEvent(BaseModel):
    type:   str = "run.in_progress"
    run_id: str

class RunOutputPartEvent(BaseModel):
    type: str = "run.output.part"
    run_id: str
    part: MessagePart

class RunCompletedEvent(BaseModel):
    type: str = "run.completed"
    run:  Run

class RunFailedEvent(BaseModel):
    type:  str = "run.failed"
    run_id: str
    error: str


# ── Helper constructors ───────────────────────────────────────────────────────

def text_part(content: str, name: str | None = None) -> MessagePart:
    return MessagePart(content=content, content_type="text/plain", name=name)

def json_part(data: dict[str, Any], name: str | None = None) -> MessagePart:
    return MessagePart(content=json.dumps(data), content_type="application/json", name=name)

def text_message(content: str) -> Message:
    return Message(parts=[text_part(content)])

def json_message(data: dict[str, Any], name: str | None = None) -> Message:
    return Message(parts=[json_part(data, name)])


# ── Helper extractors ─────────────────────────────────────────────────────────

def extract_text(messages: list[Message]) -> str:
    """Pull the first text/plain part from a list of messages."""
    for msg in messages:
        for part in msg.parts:
            if part.content_type == "text/plain":
                return part.content
    return ""

def extract_json(messages: list[Message], name: str | None = None) -> dict[str, Any]:
    """Pull the first application/json part (optionally by name)."""
    for msg in messages:
        for part in msg.parts:
            if part.content_type == "application/json":
                if name is None or part.name == name:
                    return json.loads(part.content)
    return {}

def get_run_text(run: Run) -> str:
    """Get text output from a completed Run."""
    if not run.output:
        return ""
    return extract_text(run.output)

def get_run_json(run: Run, name: str | None = None) -> dict[str, Any]:
    """Get JSON output from a completed Run."""
    if not run.output:
        return {}
    return extract_json(run.output, name)

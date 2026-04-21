"""
A2A-compliant Pydantic models.
Follows the Agent-to-Agent (A2A) open protocol spec.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field


# ── Part types ───────────────────────────────────────────────────────────────

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    metadata: Optional[dict[str, Any]] = None


class DataPart(BaseModel):
    type: Literal["data"] = "data"
    data: dict[str, Any]
    metadata: Optional[dict[str, Any]] = None


Part = Annotated[Union[TextPart, DataPart], Field(discriminator="type")]


# ── Message ──────────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]
    metadata: Optional[dict[str, Any]] = None


# ── Artifact ─────────────────────────────────────────────────────────────────

class Artifact(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parts: list[Part]
    index: int = 0
    append: Optional[bool] = None
    lastChunk: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None


# ── Task state ───────────────────────────────────────────────────────────────

class TaskState(str, Enum):
    submitted    = "submitted"
    working      = "working"
    input_required = "input-required"
    completed    = "completed"
    cancelled    = "cancelled"
    failed       = "failed"


class TaskStatus(BaseModel):
    state: TaskState
    message: Optional[Message] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Task(BaseModel):
    id: str
    sessionId: Optional[str] = None
    status: TaskStatus
    artifacts: Optional[list[Artifact]] = None
    history: Optional[list[Message]] = None
    metadata: Optional[dict[str, Any]] = None


# ── Push notifications ────────────────────────────────────────────────────────

class PushNotificationConfig(BaseModel):
    url: str
    token: Optional[str] = None


# ── Request params ────────────────────────────────────────────────────────────

class TaskSendParams(BaseModel):
    id: str
    sessionId: Optional[str] = None
    message: Message
    historyLength: Optional[int] = None
    pushNotification: Optional[PushNotificationConfig] = None
    metadata: Optional[dict[str, Any]] = None


# ── SSE event models ─────────────────────────────────────────────────────────

class TaskStatusUpdateEvent(BaseModel):
    id: str
    status: TaskStatus
    final: bool = False
    metadata: Optional[dict[str, Any]] = None


class TaskArtifactUpdateEvent(BaseModel):
    id: str
    artifact: Artifact
    metadata: Optional[dict[str, Any]] = None


# ── Agent Card ───────────────────────────────────────────────────────────────

class AgentCapabilities(BaseModel):
    streaming: bool = True
    pushNotifications: bool = False
    stateTransitionHistory: bool = True


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: Optional[list[str]] = None
    examples: Optional[list[str]] = None
    inputModes: Optional[list[str]] = None
    outputModes: Optional[list[str]] = None


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill]
    defaultInputModes: list[str] = ["text"]
    defaultOutputModes: list[str] = ["text"]
    authentication: Optional[dict[str, Any]] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def text_part(content: str) -> TextPart:
    return TextPart(text=content)


def data_part(data: dict[str, Any]) -> DataPart:
    return DataPart(data=data)


def text_artifact(name: str, content: str, index: int = 0) -> Artifact:
    return Artifact(name=name, parts=[TextPart(text=content)], index=index)


def extract_text(message: Message) -> str:
    """Return concatenated text from all TextParts in a message."""
    return "\n".join(p.text for p in message.parts if isinstance(p, TextPart))


def extract_data(message: Message) -> dict[str, Any]:
    """Return merged data dict from all DataParts in a message."""
    result: dict[str, Any] = {}
    for p in message.parts:
        if isinstance(p, DataPart):
            result.update(p.data)
    return result


def get_artifact_text(task: Task, name: str) -> str:
    """Extract text content from a named artifact in a Task."""
    artifact = next(
        (a for a in (task.artifacts or []) if a.name == name), None
    )
    if artifact is None:
        raise ValueError(f"Artifact '{name}' not found in task {task.id}")
    return "\n".join(p.text for p in artifact.parts if isinstance(p, TextPart))

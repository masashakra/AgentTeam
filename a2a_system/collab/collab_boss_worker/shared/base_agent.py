"""
A2A-compliant BaseAgent — full spec implementation.

Endpoints:
  GET  /.well-known/agent.json          — agent discovery card
  POST /tasks/send                      — synchronous task execution
  POST /tasks/sendSubscribe             — SSE streaming task execution
  GET  /tasks/{task_id}                 — poll task status
  POST /tasks/{task_id}/cancel          — cancel an in-flight task
  POST /tasks/push-notification         — receive push notification callbacks

A2A features:
  - Auto-registers with AgentRegistry on startup, deregisters on shutdown
  - Bearer token authentication on every inbound request (if AGENT_TOKEN set)
  - Sends push notification webhook when task completes (if client requested it)
"""
from __future__ import annotations

import asyncio
import os
import urllib.parse
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.logger import elapsed_ms, log_receive, log_reply, start_timer
from shared.models import (
    AgentCard, Artifact, Message, PushNotificationConfig, Task,
    TaskArtifactUpdateEvent, TaskSendParams, TaskState, TaskStatus,
    TaskStatusUpdateEvent, text_part,
)

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:8099")
AGENT_TOKEN  = os.getenv("AGENT_TOKEN", "")

_bearer = HTTPBearer(auto_error=False)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {AGENT_TOKEN}"} if AGENT_TOKEN else {}


def _check_auth(credentials: Optional[HTTPAuthorizationCredentials]) -> None:
    if not AGENT_TOKEN:
        return
    if credentials is None or credentials.credentials != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing token")


def _sse(event: TaskStatusUpdateEvent | TaskArtifactUpdateEvent) -> str:
    return f"data: {event.model_dump_json()}\n\n"


class BaseAgent:
    """Full A2A-protocol FastAPI wrapper with discovery, auth, and push notifications."""

    def __init__(self, card: AgentCard) -> None:
        self.card = card
        self._tasks: dict[str, Task] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._push_configs: dict[str, PushNotificationConfig] = {}

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            await self._register()
            yield
            await self._deregister()

        self.app = FastAPI(title=card.name, lifespan=lifespan)
        self._setup_routes()

    # ── Registry ──────────────────────────────────────────────────────────────

    async def _register(self) -> None:
        async with httpx.AsyncClient() as http:
            try:
                await http.post(
                    f"{REGISTRY_URL}/register",
                    json=self.card.model_dump(mode="json"),
                    headers=_auth_headers(),
                    timeout=5.0,
                )
                print(f"[{self.card.name}] Registered with registry at {REGISTRY_URL}", flush=True)
            except Exception as exc:
                print(f"[{self.card.name}] Registry registration failed: {exc}", flush=True)

    async def _deregister(self) -> None:
        encoded = urllib.parse.quote(self.card.name)
        async with httpx.AsyncClient() as http:
            try:
                await http.delete(
                    f"{REGISTRY_URL}/agents/{encoded}",
                    headers=_auth_headers(),
                    timeout=5.0,
                )
            except Exception:
                pass

    # ── Push notifications ─────────────────────────────────────────────────────

    async def _send_push_notification(self, task: Task) -> None:
        config = self._push_configs.get(task.id)
        if config is None:
            return
        headers: dict[str, str] = {}
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"
        async with httpx.AsyncClient() as http:
            try:
                await http.post(
                    config.url,
                    json=task.model_dump(mode="json"),
                    headers=headers,
                    timeout=10.0,
                )
            except Exception as exc:
                print(f"[{self.card.name}] Push notification failed: {exc}", flush=True)
        self._push_configs.pop(task.id, None)

    # ── Route setup ───────────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        app = self.app

        # ── Agent discovery ──────────────────────────────────────────────────
        @app.get("/.well-known/agent.json", response_model=AgentCard)
        async def agent_card() -> AgentCard:
            return self.card

        # ── Synchronous send ─────────────────────────────────────────────────
        @app.post("/tasks/send", response_model=Task)
        async def tasks_send(
            params: TaskSendParams,
            http_request: Request,
            credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
        ) -> Task:
            _check_auth(credentials)
            sender = http_request.headers.get("X-Sender", "Unknown")
            task = self._init_task(params)
            log_receive(self.card.name, sender, params.id, "skill=send")
            start_timer(f"{self.card.name}-{params.id}")

            if params.pushNotification:
                self._push_configs[params.id] = params.pushNotification

            task.status = TaskStatus(state=TaskState.working)
            task.history = [params.message]

            try:
                artifacts = await self.handle(params.message, params.id)
                task.status = TaskStatus(state=TaskState.completed)
                task.artifacts = artifacts
            except Exception as exc:
                error_msg = str(exc) or repr(exc) or "Unknown error"
                print(f"[{self.card.name}] Task {params.id} failed: {error_msg}", flush=True)
                task.status = TaskStatus(
                    state=TaskState.failed,
                    message=Message(role="agent", parts=[text_part(error_msg)]),
                )

            t = elapsed_ms(f"{self.card.name}-{params.id}")
            log_reply(
                self.card.name, sender, params.id,
                task.status.state.value,
                f"{len(task.artifacts or [])} artifact(s)",
                elapsed=t,
            )
            await self._send_push_notification(task)
            return task

        # ── SSE streaming send ───────────────────────────────────────────────
        @app.post("/tasks/sendSubscribe")
        async def tasks_subscribe(
            params: TaskSendParams,
            http_request: Request,
            credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
        ):
            _check_auth(credentials)
            sender = http_request.headers.get("X-Sender", "Unknown")
            task = self._init_task(params)
            task.history = [params.message]
            log_receive(self.card.name, sender, params.id, "skill=sendSubscribe")

            if params.pushNotification:
                self._push_configs[params.id] = params.pushNotification

            queue: asyncio.Queue = asyncio.Queue()

            async def run() -> None:
                try:
                    task.status = TaskStatus(state=TaskState.working)
                    await queue.put(("status", task.status, False))
                    artifacts = await self.handle(params.message, params.id)
                    task.artifacts = artifacts
                    for artifact in artifacts:
                        await queue.put(("artifact", artifact, False))
                    task.status = TaskStatus(state=TaskState.completed)
                    await queue.put(("status", task.status, True))
                    await self._send_push_notification(task)
                except asyncio.CancelledError:
                    task.status = TaskStatus(state=TaskState.cancelled)
                    await queue.put(("status", task.status, True))
                except Exception as exc:
                    task.status = TaskStatus(
                        state=TaskState.failed,
                        message=Message(role="agent", parts=[text_part(str(exc))]),
                    )
                    await queue.put(("status", task.status, True))
                finally:
                    await queue.put(None)
                    self._running.pop(params.id, None)

            asyncio_task = asyncio.create_task(run())
            self._running[params.id] = asyncio_task

            async def event_stream() -> AsyncGenerator[str, None]:
                yield _sse(TaskStatusUpdateEvent(
                    id=params.id,
                    status=TaskStatus(state=TaskState.submitted),
                    final=False,
                ))
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    kind, data, final = item
                    if kind == "status":
                        yield _sse(TaskStatusUpdateEvent(id=params.id, status=data, final=final))
                    elif kind == "artifact":
                        yield _sse(TaskArtifactUpdateEvent(id=params.id, artifact=data))

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        # ── Poll task ────────────────────────────────────────────────────────
        @app.get("/tasks/{task_id}", response_model=Task)
        async def get_task(
            task_id: str,
            credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
        ) -> Task:
            _check_auth(credentials)
            task = self._tasks.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
            return task

        # ── Cancel task ──────────────────────────────────────────────────────
        @app.post("/tasks/{task_id}/cancel", response_model=Task)
        async def cancel_task(
            task_id: str,
            credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
        ) -> Task:
            _check_auth(credentials)
            task = self._tasks.get(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
            if task.status.state not in (TaskState.submitted, TaskState.working):
                raise HTTPException(
                    status_code=400, detail=f"Task is already {task.status.state.value}"
                )
            asyncio_task = self._running.get(task_id)
            if asyncio_task:
                asyncio_task.cancel()
            else:
                task.status = TaskStatus(state=TaskState.cancelled)
            return task

        # ── Push notification receiver ────────────────────────────────────────
        @app.post("/tasks/push-notification")
        async def receive_push_notification(
            task: Task,
            credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
        ) -> dict:
            _check_auth(credentials)
            self._tasks[task.id] = task
            print(
                f"[{self.card.name}] Push notification received: "
                f"task={task.id} state={task.status.state.value}",
                flush=True,
            )
            return {"status": "received", "task_id": task.id}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _init_task(self, params: TaskSendParams) -> Task:
        task = Task(
            id=params.id,
            sessionId=params.sessionId,
            status=TaskStatus(state=TaskState.submitted),
        )
        self._tasks[params.id] = task
        return task

    async def handle(self, message: Message, task_id: str) -> list[Artifact]:  # pragma: no cover
        raise NotImplementedError

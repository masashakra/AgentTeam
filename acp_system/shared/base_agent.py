"""
ACP BaseAgent — FastAPI wrapper implementing the 4 standard ACP endpoints:

  GET  /agents              — agent discovery manifest
  POST /runs                — synchronous run (returns completed Run)
  POST /runs/stream         — SSE streaming run
  GET  /runs/{run_id}       — poll a run by ID
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from shared.models import (
    AgentManifest, AgentsResponse, Message, Run, RunCompletedEvent,
    RunCreatedEvent, RunFailedEvent, RunInProgressEvent, RunOutputPartEvent,
    RunRequest, RunStatus,
)


class BaseACPAgent:
    def __init__(self, manifest: AgentManifest) -> None:
        self._manifest = manifest
        self._runs: dict[str, Run] = {}
        self.app = FastAPI(title=manifest.name)
        self._setup_routes()

    def _setup_routes(self) -> None:

        # ── GET /agents ───────────────────────────────────────────────────────
        @self.app.get("/agents", response_model=AgentsResponse)
        def list_agents() -> AgentsResponse:
            return AgentsResponse(agents=[self._manifest])

        # ── POST /runs ────────────────────────────────────────────────────────
        @self.app.post("/runs", response_model=Run)
        async def create_run(request: RunRequest) -> Run:
            run = Run(
                agent_name=request.agent_name,
                input=request.input,
                status=RunStatus.created,
            )
            self._runs[run.run_id] = run

            # Execute synchronously
            run.status = RunStatus.in_progress
            try:
                output = await self.handle(run.input, run.run_id)
                run.output = output
                run.status = RunStatus.completed
            except Exception as exc:
                run.status = RunStatus.failed
                run.error = str(exc)
            finally:
                run.finished_at = datetime.now(timezone.utc).isoformat()

            self._runs[run.run_id] = run
            return run

        # ── POST /runs/stream ─────────────────────────────────────────────────
        @self.app.post("/runs/stream")
        async def stream_run(request: RunRequest) -> StreamingResponse:
            run = Run(
                agent_name=request.agent_name,
                input=request.input,
                status=RunStatus.created,
            )
            self._runs[run.run_id] = run

            queue: asyncio.Queue = asyncio.Queue()

            async def background() -> None:
                run.status = RunStatus.in_progress
                await queue.put(RunInProgressEvent(run_id=run.run_id))
                try:
                    output = await self.handle(run.input, run.run_id)
                    run.output = output
                    run.status = RunStatus.completed
                    run.finished_at = datetime.now(timezone.utc).isoformat()
                    # Emit each output part
                    for msg in output:
                        for part in msg.parts:
                            await queue.put(RunOutputPartEvent(run_id=run.run_id, part=part))
                    await queue.put(RunCompletedEvent(run=run))
                except Exception as exc:
                    run.status = RunStatus.failed
                    run.error = str(exc)
                    run.finished_at = datetime.now(timezone.utc).isoformat()
                    await queue.put(RunFailedEvent(run_id=run.run_id, error=str(exc)))
                finally:
                    await queue.put(None)  # sentinel

            asyncio.create_task(background())

            async def generate() -> AsyncGenerator[str, None]:
                # Emit run.created first
                yield f"data: {RunCreatedEvent(run_id=run.run_id, agent_name=run.agent_name).model_dump_json()}\n\n"
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield f"data: {event.model_dump_json()}\n\n"

            return StreamingResponse(generate(), media_type="text/event-stream")

        # ── GET /runs/{run_id} ────────────────────────────────────────────────
        @self.app.get("/runs/{run_id}", response_model=Run)
        def get_run(run_id: str) -> Run:
            run = self._runs.get(run_id)
            if not run:
                raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
            return run

    # ── Subclasses implement this ─────────────────────────────────────────────

    async def handle(self, messages: list[Message], run_id: str) -> list[Message]:
        """Process input messages and return output messages."""
        raise NotImplementedError

    def serve(self, port: int) -> None:
        uvicorn.run(self.app, host="0.0.0.0", port=port, log_level="warning")

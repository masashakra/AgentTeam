"""
A2A Agent Registry — port 8099
Central discovery service. Agents register on startup, deregister on shutdown.
Clients query by name, skill ID, or list all.

Endpoints:
  GET  /.well-known/agent-registry.json  — registry info card
  POST /register                         — register an agent (body: AgentCard)
  DELETE /agents/{name}                  — deregister an agent
  GET  /agents                           — list all registered agents
  GET  /agents/{name}                    — get one agent card by name
  GET  /agents/skill/{skill_id}          — find agents by skill ID
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Import AgentCard from whichever shared/ is reachable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "a2a_system/collab/collab_boss_worker"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "a2a_system/collab/collab_round_table"))

from shared.models import AgentCard

app = FastAPI(title="A2A Agent Registry")

# In-memory store: name → AgentCard
_registry: dict[str, AgentCard] = {}

REGISTRY_TOKEN = os.getenv("AGENT_TOKEN", "")


def _check_auth(request: Request) -> None:
    if not REGISTRY_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {REGISTRY_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Discovery card ─────────────────────────────────────────────────────────────

@app.get("/.well-known/agent-registry.json")
def registry_card() -> dict[str, Any]:
    return {
        "name": "A2A Agent Registry",
        "url": "http://localhost:8099",
        "version": "1.0.0",
        "description": "Central agent discovery service for the A2A multi-agent system.",
        "endpoints": {
            "register":    "POST /register",
            "deregister":  "DELETE /agents/{name}",
            "list":        "GET /agents",
            "get_by_name": "GET /agents/{name}",
            "get_by_skill":"GET /agents/skill/{skill_id}",
        },
    }


# ── Registration ───────────────────────────────────────────────────────────────

@app.post("/register", status_code=200)
async def register(card: AgentCard, request: Request) -> dict[str, str]:
    _check_auth(request)
    _registry[card.name] = card
    print(f"[Registry] Registered: {card.name!r} → {card.url}", flush=True)
    return {"status": "registered", "name": card.name}


@app.delete("/agents/{name}")
async def deregister(name: str, request: Request) -> dict[str, str]:
    _check_auth(request)
    decoded = urllib.parse.unquote(name)
    _registry.pop(decoded, None)
    print(f"[Registry] Deregistered: {decoded!r}", flush=True)
    return {"status": "deregistered", "name": decoded}


# ── Discovery ──────────────────────────────────────────────────────────────────

@app.get("/agents")
def list_agents() -> list[dict]:
    return [c.model_dump(mode="json") for c in _registry.values()]


@app.get("/agents/skill/{skill_id}")
def find_by_skill(skill_id: str) -> list[dict]:
    matches = [
        c for c in _registry.values()
        if any(s.id == skill_id for s in c.skills)
    ]
    return [c.model_dump(mode="json") for c in matches]


@app.get("/agents/{name}")
def get_agent(name: str) -> dict:
    decoded = urllib.parse.unquote(name)
    card = _registry.get(decoded)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Agent {decoded!r} not found")
    return card.model_dump(mode="json")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("registry:app", host="0.0.0.0", port=8099, reload=False)

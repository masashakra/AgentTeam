"""
shared/discover.py — A2A agent discovery helpers.
Queries the AgentRegistry to find agents by name or skill ID.
No hardcoded URLs — all discovery is dynamic at call time.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from shared.models import AgentCard

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:8099")
AGENT_TOKEN  = os.getenv("AGENT_TOKEN", "")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {AGENT_TOKEN}"} if AGENT_TOKEN else {}


async def find_agent_by_name(name: str, timeout: float = 5.0) -> AgentCard:
    """Return the AgentCard for a registered agent by exact name."""
    import urllib.parse
    encoded = urllib.parse.quote(name)
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{REGISTRY_URL}/agents/{encoded}",
            headers=_headers(),
            timeout=timeout,
        )
        resp.raise_for_status()
        return AgentCard.model_validate(resp.json())


async def find_agents_by_skill(skill_id: str, timeout: float = 5.0) -> list[AgentCard]:
    """Return all AgentCards that expose a given skill ID."""
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{REGISTRY_URL}/agents/skill/{skill_id}",
            headers=_headers(),
            timeout=timeout,
        )
        resp.raise_for_status()
        return [AgentCard.model_validate(c) for c in resp.json()]


async def list_agents(timeout: float = 5.0) -> list[AgentCard]:
    """Return all registered agents."""
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{REGISTRY_URL}/agents",
            headers=_headers(),
            timeout=timeout,
        )
        resp.raise_for_status()
        return [AgentCard.model_validate(c) for c in resp.json()]

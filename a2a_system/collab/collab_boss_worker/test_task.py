"""
test_task.py — sends a coding task to the Boss Agent and prints results.

Two modes:
  python test_task.py          — synchronous /tasks/send (default)
  python test_task.py --stream — SSE streaming via /tasks/sendSubscribe

The Boss Agent must already be running (use run_all.py first).
"""
from __future__ import annotations

import asyncio
import json
import sys
import textwrap
import uuid

import httpx

BOSS_SEND_URL      = "http://localhost:8000/tasks/send"
BOSS_STREAM_URL    = "http://localhost:8000/tasks/sendSubscribe"
TASK = "Write a Python function that merges two sorted lists"


def banner(title: str) -> None:
    width = 70
    print("\n" + "─" * width)
    print(f"  {title}")
    print("─" * width)


def _build_payload(task_id: str) -> dict:
    """Build an A2A-compliant TaskSendParams payload."""
    return {
        "id": task_id,
        "message": {
            "role": "user",
            "parts": [
                {"type": "text", "text": TASK}
            ],
        },
    }


def _print_artifact(name: str, parts: list[dict]) -> None:
    """Pretty-print a single A2A Artifact."""
    content = ""
    for part in parts:
        if part.get("type") == "text":
            content += part.get("text", "")
        elif part.get("type") == "data":
            content += json.dumps(part.get("data", {}), indent=2)

    # Strip markdown code fences if present
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Remove first line (```json or ```) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        content = "\n".join(inner).strip()

    # Pretty-print if the content looks like JSON
    try:
        parsed = json.loads(content.strip())
        content = json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, ValueError):
        pass

    banner(f"Artifact: {name}")
    print(textwrap.indent(content, "  "))


# ── Synchronous mode ─────────────────────────────────────────────────────────

async def run_sync() -> None:
    task_id = str(uuid.uuid4())
    payload = _build_payload(task_id)

    banner("Sending task to Boss Agent  [sync /tasks/send]")
    print(f"  Task : {TASK}")
    print(f"  ID   : {task_id}")

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(BOSS_SEND_URL, json=payload,
                                         headers={"X-Sender": "test_task.py"})
            response.raise_for_status()
        except httpx.ConnectError:
            print("ERROR: Cannot connect to Boss Agent on port 8000.")
            print("       Start all agents first:  python run_all.py")
            sys.exit(1)
        except httpx.HTTPStatusError as exc:
            print(f"ERROR: HTTP {exc.response.status_code} — {exc.response.text}")
            sys.exit(1)

    task = response.json()

    banner("Boss Agent Response")
    status = task.get("status", {})
    print(f"  Task ID : {task.get('id')}")
    print(f"  State   : {status.get('state')}")
    if status.get("message"):
        msg = status["message"]
        err_text = " ".join(
            p.get("text", "") for p in msg.get("parts", []) if p.get("type") == "text"
        )
        print(f"  Error   : {err_text}")

    for artifact in task.get("artifacts") or []:
        name  = artifact.get("name", f"artifact-{artifact.get('index', 0)}")
        parts = artifact.get("parts", [])
        _print_artifact(name, parts)

    print("\n" + "─" * 70 + "\n")


# ── SSE streaming mode ────────────────────────────────────────────────────────

async def run_stream() -> None:
    task_id = str(uuid.uuid4())
    payload = _build_payload(task_id)

    banner("Sending task to Boss Agent  [SSE /tasks/sendSubscribe]")
    print(f"  Task : {TASK}")
    print(f"  ID   : {task_id}")
    print()

    artifacts: list[dict] = []

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            async with client.stream(
                "POST", BOSS_STREAM_URL, json=payload,
                headers={"X-Sender": "test_task.py", "Accept": "text/event-stream"},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Status update
                    if "status" in event and "artifact" not in event:
                        state = event["status"].get("state", "?")
                        final = event.get("final", False)
                        print(f"  [state] {state}" + (" ✓" if final else ""))
                        if state == "failed":
                            msg = event["status"].get("message", {})
                            err = " ".join(
                                p.get("text", "")
                                for p in msg.get("parts", [])
                                if p.get("type") == "text"
                            )
                            print(f"  [error] {err}")

                    # Artifact update
                    if "artifact" in event:
                        art = event["artifact"]
                        artifacts.append(art)
                        name = art.get("name", f"artifact-{art.get('index', 0)}")
                        print(f"  [artifact received] {name}")

        except httpx.ConnectError:
            print("ERROR: Cannot connect to Boss Agent on port 8000.")
            print("       Start all agents first:  python run_all.py")
            sys.exit(1)
        except httpx.HTTPStatusError as exc:
            print(f"ERROR: HTTP {exc.response.status_code} — {exc.response.text}")
            sys.exit(1)

    for artifact in artifacts:
        name  = artifact.get("name", f"artifact-{artifact.get('index', 0)}")
        parts = artifact.get("parts", [])
        _print_artifact(name, parts)

    print("\n" + "─" * 70 + "\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--stream" in sys.argv:
        asyncio.run(run_stream())
    else:
        asyncio.run(run_sync())

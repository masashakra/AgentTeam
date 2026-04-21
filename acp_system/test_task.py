"""
End-to-end test for the ACP system.

Usage:
  python3 test_task.py           # sync POST /runs
  python3 test_task.py --stream  # SSE POST /runs/stream
"""
from __future__ import annotations

import json
import sys
import httpx

BOSS_URL = "http://localhost:9000"

TASK = (
    "Write a Python function that merges two sorted lists into one sorted list "
    "without using the built-in sort function. Include proper docstrings, type hints, "
    "and test cases for normal input, empty lists, and lists with duplicates."
)


def _strip_fences(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def run_sync() -> None:
    print(f"[test] Sending task to BossAgent (sync)...\n")
    payload = {
        "agent_name": "BossAgent",
        "input": [{"parts": [{"content": TASK, "content_type": "text/plain"}]}],
    }
    with httpx.Client(timeout=600) as client:
        resp = client.post(f"{BOSS_URL}/runs", json=payload)
        resp.raise_for_status()

    run = resp.json()
    print(f"[test] Run ID  : {run['run_id']}")
    print(f"[test] Status  : {run['status']}")

    output = run.get("output") or []
    code   = ""
    review = {}

    for msg in output:
        for part in msg.get("parts", []):
            if part.get("content_type") == "text/plain":
                code = part["content"]
            elif part.get("content_type") == "application/json":
                review = json.loads(part["content"])

    if code:
        print("\n" + "="*60)
        print("IMPLEMENTATION")
        print("="*60)
        print(_strip_fences(code))

    if review:
        print("\n" + "="*60)
        print("REVIEW VERDICT")
        print("="*60)
        verdict = review.get("verdict", "?").upper()
        colour  = "\033[92m" if verdict == "PASS" else "\033[91m"
        reset   = "\033[0m"
        print(f"Verdict   : {colour}{verdict}{reset}")
        print(f"Summary   : {review.get('summary', '')}")
        issues  = review.get("issues", [])
        if issues:
            print(f"Issues    :")
            for i in issues:
                print(f"  • {i}")
        suggestions = review.get("suggestions", [])
        if suggestions:
            print(f"Suggestions:")
            for s in suggestions:
                print(f"  • {s}")

    if run.get("error"):
        print(f"\n[test] ERROR: {run['error']}")


def run_stream() -> None:
    print(f"[test] Sending task to BossAgent (SSE stream)...\n")
    payload = {
        "agent_name": "BossAgent",
        "input": [{"parts": [{"content": TASK, "content_type": "text/plain"}]}],
    }

    code   = ""
    review = {}

    with httpx.Client(timeout=600) as client:
        with client.stream("POST", f"{BOSS_URL}/runs/stream", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")
                print(f"[event] {etype}")

                if etype == "run.output.part":
                    part = event.get("part", {})
                    if part.get("content_type") == "text/plain":
                        code = part["content"]
                    elif part.get("content_type") == "application/json":
                        review = json.loads(part["content"])

                elif etype == "run.completed":
                    run = event.get("run", {})
                    print(f"[test] Run ID: {run.get('run_id')}")
                    for msg in run.get("output", []):
                        for part in msg.get("parts", []):
                            if part.get("content_type") == "text/plain":
                                code = part["content"]
                            elif part.get("content_type") == "application/json":
                                review = json.loads(part["content"])

                elif etype == "run.failed":
                    print(f"[test] FAILED: {event.get('error')}")
                    return

    if code:
        print("\n" + "="*60)
        print("IMPLEMENTATION")
        print("="*60)
        print(_strip_fences(code))

    if review:
        print("\n" + "="*60)
        print("REVIEW VERDICT")
        print("="*60)
        verdict = review.get("verdict", "?").upper()
        colour  = "\033[92m" if verdict == "PASS" else "\033[91m"
        reset   = "\033[0m"
        print(f"Verdict   : {colour}{verdict}{reset}")
        print(f"Summary   : {review.get('summary', '')}")
        issues = review.get("issues", [])
        if issues:
            print("Issues    :")
            for i in issues:
                print(f"  • {i}")
        suggestions = review.get("suggestions", [])
        if suggestions:
            print("Suggestions:")
            for s in suggestions:
                print(f"  • {s}")


if __name__ == "__main__":
    if "--stream" in sys.argv:
        run_stream()
    else:
        run_sync()

"""
Shared handoff logger — records every agent-to-agent interaction.
Writes to:
  - stdout (coloured, compact)
  - logs/session.log (full detail, human-readable)
  - logs/comms.jsonl (per-message JSONL)
  - logs/metrics.jsonl (per-event metrics JSONL)
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "session.log"
COMMS_JSONL = LOG_DIR / "comms.jsonl"
METRICS_JSONL = LOG_DIR / "metrics.jsonl"

_COLORS: dict[str, str] = {
    "Client":         "\033[97m",
    "BossAgent":      "\033[95m",
    "PlannerAgent":   "\033[94m",
    "CoderAgent":     "\033[92m",
    "ReviewerAgent":  "\033[93m",
}
_RESET  = "\033[0m"
_ARROW  = "\033[90m→\033[0m"
_DIM    = "\033[90m"
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"


def _color(name: str) -> str:
    return _COLORS.get(name, "\033[96m")


def _file(line: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _file_block(title: str, content: str) -> None:
    """Write a full content block to the log file."""
    sep = "·" * 60
    _file(f"  ┌─ {title}")
    for line in content.splitlines():
        _file(f"  │  {line}")
    _file(f"  └─ {sep}")


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _now_iso() -> str:
    return datetime.now().isoformat()


def _append_comms(obj: dict) -> None:
    """Append a communication event to JSONL log."""
    with COMMS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def _append_metrics(obj: dict) -> None:
    """Append a metric event to JSONL log."""
    with METRICS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


# ── Public timers and session ────────────────────────────────────────────────

_timers: dict[str, float] = {}
_session_id: str = ""

def set_session_id(session_id: str) -> None:
    """Set the current session ID (called at start)."""
    global _session_id
    _session_id = session_id


def start_timer(key: str) -> None:
    _timers[key] = time.perf_counter()


def elapsed_ms(key: str) -> str:
    if key not in _timers:
        return "?ms"
    ms = (time.perf_counter() - _timers.pop(key)) * 1000
    return f"{ms:.0f}ms"


# ── Log functions ─────────────────────────────────────────────────────────────

def log_send(
    sender: str,
    receiver: str,
    task_id: str,
    summary: str,
    payload: str | None = None,
) -> None:
    ts = _ts()
    chars = f"  {_DIM}{len(payload)} chars{_RESET}" if payload else ""
    console = (
        f"[{ts}] "
        f"{_color(sender)}[{sender}]{_RESET} "
        f"{_ARROW} "
        f"{_color(receiver)}[{receiver}]{_RESET} "
        f"{_DIM}{summary}{_RESET}"
        f"{chars}"
    )
    print(console, flush=True)

    plain = f"[{ts}] SEND  {sender} → {receiver}  task={task_id}  {summary}"
    if payload:
        plain += f"  ({len(payload)} chars)"
    _file(plain)
    if payload:
        _file_block("PAYLOAD", payload)

    # JSONL logging
    _append_comms({
        "timestamp": _now_iso(),
        "session_id": _session_id,
        "type": "send",
        "sender": sender,
        "receiver": receiver,
        "task_id": task_id,
        "summary": summary,
        "payload_size": len(payload) if payload else 0,
    })


def log_receive(
    receiver: str,
    sender: str,
    task_id: str,
    summary: str,
) -> None:
    ts = _ts()
    console = (
        f"[{ts}] "
        f"{_color(receiver)}[{receiver}]{_RESET} "
        f"received from "
        f"{_color(sender)}[{sender}]{_RESET} "
        f"{_DIM}{summary}{_RESET}"
    )
    print(console, flush=True)
    _file(f"[{ts}] RECV  {sender} → {receiver}  task={task_id}  {summary}")


def log_reply(
    sender: str,
    receiver: str,
    task_id: str,
    status: str,
    summary: str,
    payload: str | None = None,
    elapsed: str | None = None,
) -> None:
    ts = _ts()
    status_color = _GREEN if status == "completed" else _RED
    timing = f"  {_CYAN}{elapsed}{_RESET}" if elapsed else ""
    chars = f"  {_DIM}{len(payload)} chars{_RESET}" if payload else ""
    console = (
        f"[{ts}] "
        f"{_color(sender)}[{sender}]{_RESET} "
        f"{_ARROW} "
        f"{_color(receiver)}[{receiver}]{_RESET} "
        f"{status_color}[{status}]{_RESET} "
        f"{_DIM}{summary}{_RESET}"
        f"{chars}{timing}"
    )
    print(console, flush=True)

    plain = f"[{ts}] REPLY {sender} → {receiver}  task={task_id}  [{status}] {summary}"
    if payload:
        plain += f"  ({len(payload)} chars)"
    if elapsed:
        plain += f"  {elapsed}"
    _file(plain)
    if payload:
        _file_block("CONTENT", payload)

    # JSONL logging
    _append_comms({
        "timestamp": _now_iso(),
        "session_id": _session_id,
        "type": "reply",
        "sender": sender,
        "receiver": receiver,
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "payload_size": len(payload) if payload else 0,
        "elapsed_ms": int(elapsed.rstrip("ms")) if elapsed else None,
    })


def log_verdict(verdict: str, issues: list[str], suggestions: list[str], attempt: int) -> None:
    ts = _ts()
    v_color = _GREEN if verdict == "pass" else _RED
    console = (
        f"[{ts}] "
        f"{_YELLOW}[ReviewVerdict]{_RESET} "
        f"attempt={attempt}  "
        f"{v_color}{verdict.upper()}{_RESET}"
    )
    if verdict == "fail" and issues:
        console += f"  {_DIM}{len(issues)} issue(s){_RESET}"
    print(console, flush=True)

    _file(f"[{ts}] VERDICT  attempt={attempt}  {verdict.upper()}")
    for i, issue in enumerate(issues, 1):
        _file(f"  issue[{i}]: {issue}")
    for i, sug in enumerate(suggestions, 1):
        _file(f"  suggestion[{i}]: {sug}")

    # JSONL logging
    _append_metrics({
        "timestamp": _now_iso(),
        "session_id": _session_id,
        "event": "code_review",
        "attempt": attempt,
        "verdict": verdict,
        "issues_count": len(issues),
        "suggestions_count": len(suggestions),
        "issues": issues,
        "suggestions": suggestions,
    })


def log_gemini(agent: str, label: str, content: str) -> None:
    """Log a direct Gemini call (not agent-to-agent)."""
    ts = _ts()
    console = (
        f"[{ts}] "
        f"{_color(agent)}[{agent}]{_RESET} "
        f"{_CYAN}Gemini/{label}{_RESET} "
        f"{_DIM}{len(content)} chars{_RESET}"
    )
    print(console, flush=True)
    _file(f"[{ts}] GEMINI  agent={agent}  label={label}  ({len(content)} chars)")
    _file_block(f"Gemini {label}", content)


def log_session_start(task: str) -> None:
    session_id = str(uuid.uuid4())
    set_session_id(session_id)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "═" * 70
    print(f"\n{sep}")
    print(f"  SESSION START  {ts}")
    print(f"  Session ID: {session_id}")
    print(f"  Task: {task}")
    print(f"{sep}\n")
    _file(sep)
    _file(f"SESSION START  {ts}  session_id={session_id}  task={task!r}")
    _file(sep)

    # JSONL logging
    _append_metrics({
        "timestamp": _now_iso(),
        "session_id": session_id,
        "event": "session_start",
        "task": task,
    })

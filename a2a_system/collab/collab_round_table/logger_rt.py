"""
logger_rt.py — Round Table session logger.
Completely separate from shared/logger.py. Do not import from shared/.

Log files (appended across runs):
  logs/round_table_sessions.log  — human-readable session events
  logs/round_table_comms.jsonl   — per-message JSONL
  logs/round_table_metrics.jsonl — per-event metrics JSONL
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

SESSIONS_LOG = LOG_DIR / "round_table_sessions.log"
COMMS_JSONL = LOG_DIR / "round_table_comms.jsonl"
METRICS_JSONL = LOG_DIR / "round_table_metrics.jsonl"

# ANSI color codes
_COLORS: dict[str, str] = {
    "Architect":     "\033[94m",   # blue
    "Coder":         "\033[92m",   # green
    "Debugger":      "\033[91m",   # red
    "Tester":        "\033[93m",   # yellow
    "Orchestrator":  "\033[95m",   # magenta
    "TestGenerator": "\033[96m",   # cyan
    "CodeValidator": "\033[97m",   # white
}
_RESET = "\033[0m"
_DIM   = "\033[90m"
_CYAN  = "\033[96m"
_BOLD  = "\033[1m"


def _color(name: str) -> str:
    return _COLORS.get(name, "\033[96m")


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _now_iso() -> str:
    return datetime.now().isoformat()


def _append_sessions(line: str) -> None:
    with SESSIONS_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _append_comms(obj: dict) -> None:
    with COMMS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def _append_metrics(obj: dict) -> None:
    with METRICS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


# ── Public API ────────────────────────────────────────────────────────────────

def new_session(task: str) -> str:
    """Create a new session ID, write header to sessions.log, return session_id."""
    session_id = str(uuid.uuid4())
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "═" * 70
    header = (
        f"\n{sep}\n"
        f"  ROUND TABLE SESSION  {ts}\n"
        f"  Session ID: {session_id}\n"
        f"  Task: {task}\n"
        f"{sep}"
    )
    print(f"\n{_BOLD}{sep}{_RESET}")
    print(f"  {_CYAN}ROUND TABLE SESSION{_RESET}  {ts}")
    print(f"  Session ID: {session_id}")
    print(f"  Task: {task}")
    print(f"{_BOLD}{sep}{_RESET}\n", flush=True)
    _append_sessions(header)
    return session_id


def log_round_start(session_id: str, round_num: int, max_rounds: int, task: str) -> None:
    ts = _ts()
    print(f"[{ts}] {_CYAN}[Round {round_num}/{max_rounds}]{_RESET} Starting...", flush=True)
    _append_sessions(
        f"[{ts}] ROUND_START  session={session_id}  round={round_num}/{max_rounds}"
    )
    _append_metrics({
        "session_id": session_id,
        "timestamp": _now_iso(),
        "round": round_num,
        "event": "round_start",
        "data": {"round_num": round_num, "task": task},
    })


def log_peer_message(
    session_id: str,
    sender: str,
    receiver: str,
    round_num: int,
    message_type: str,
    content: str,
) -> None:
    ts = _ts()
    print(
        f"[{ts}] {_color(sender)}[{sender}]{_RESET} \u2192 "
        f"{_color(receiver)}[{receiver}]{_RESET} "
        f"{_DIM}[{message_type}]{_RESET}",
        flush=True,
    )
    _append_sessions(
        f"[{ts}] PEER_MSG  {sender}\u2192{receiver}  round={round_num}  type={message_type}"
    )
    _append_comms({
        "session_id": session_id,
        "timestamp": _now_iso(),
        "round": round_num,
        "sender": sender,
        "receiver": receiver,
        "message_type": message_type,
        "content": content,
        "content_length": len(content),
    })


def log_round_end(session_id: str, round_num: int, agent_outputs: dict) -> None:
    ts = _ts()
    agents_done = list(agent_outputs.keys())
    print(
        f"[{ts}] {_CYAN}[Round {round_num}]{_RESET} Complete — agents: {agents_done}",
        flush=True,
    )
    _append_sessions(
        f"[{ts}] ROUND_END  session={session_id}  round={round_num}  agents={agents_done}"
    )
    _append_metrics({
        "session_id": session_id,
        "timestamp": _now_iso(),
        "round": round_num,
        "event": "round_end",
        "data": {
            "round_num": round_num,
            "messages_per_agent": {k: 1 for k in agents_done},
            "total_messages": len(agents_done),
        },
    })


def log_consensus(session_id: str, round_num: int, reason: str) -> None:
    ts = _ts()
    print(
        f"[{ts}] {_CYAN}[TERMINATION]{_RESET} reason={reason}  round={round_num}",
        flush=True,
    )
    _append_sessions(
        f"[{ts}] TERMINATION  session={session_id}  round={round_num}  reason={reason}"
    )


def log_metric(session_id: str, round_num: int, event: str, data: dict) -> None:
    _append_metrics({
        "session_id": session_id,
        "timestamp": _now_iso(),
        "round": round_num,
        "event": event,
        "data": data,
    })

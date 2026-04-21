# AgentTeam — CLAUDE.md

## Project Overview
A multi-agent A2A (Agent-to-Agent) system where a **Boss Agent** orchestrates a pipeline of three worker agents to solve coding tasks end-to-end. Built with FastAPI + Google Gemini (`gemini-2.5-flash-lite`).

## Architecture

```
Client
  └─► BossAgent (port 8000)
        ├─► PlannerAgent  (port 8001)  — produces technical_plan
        ├─► CoderAgent    (port 8002)  — produces implementation
        └─► ReviewerAgent (port 8003)  — produces pass/fail review JSON
```

### Pipeline Flow
1. **Boss** receives task → calls Gemini directly to refine/decompose it
2. **Boss → Planner** — sends refined task, gets back a step-by-step technical plan
3. **Boss → Coder** — sends plan (+ optional reviewer feedback), gets back Python code
4. **Boss → Reviewer** — sends code + original task, gets back structured JSON verdict
5. If verdict is `"fail"`, Boss retries Coder with feedback (max 2 retries / 3 attempts total)
6. Final code + review returned to client

## File Structure
```
project/
├── groq_setup/               # Shared LLM setup (both scenarios import from here)
├── collab_boss_worker/        # Boss-Worker scenario (formerly a2a_system/)
│   ├── agents/
│   │   ├── boss_agent.py       # Orchestrator, port 8000
│   │   ├── planner_agent.py    # Step-by-step planner, port 8001
│   │   ├── coder_agent.py      # Python code generator, port 8002
│   │   └── reviewer_agent.py   # Pass/fail code reviewer, port 8003
│   ├── shared/
│   │   ├── base_agent.py       # FastAPI wrapper, logs inbound RECV + REPLY with timing
│   │   ├── models.py           # Pydantic models: AgentCard, TaskRequest, TaskResponse, Artifact
│   │   └── logger.py           # Structured handoff logger (console + logs/session.log)
│   ├── logs/
│   │   └── session.log         # Full detailed log: payloads, timings, verdicts
│   ├── run_all.py              # Starts all 4 agents concurrently (coloured output per agent)
│   └── test_task.py            # End-to-end test — sends task to Boss, prints all artifacts
├── collab_round_table/        # Round Table scenario (peer-to-peer, LangGraph orchestration)
│   ├── agents/
│   │   ├── architect_agent.py      # port 8010 — design/structure
│   │   ├── coder_agent_rt.py       # port 8011 — implementation + run_python
│   │   ├── debugger_agent.py       # port 8012 — bug finding/fixing
│   │   ├── tester_agent.py         # port 8013 — edge cases/correctness
│   │   ├── test_generator_agent.py # port 8014 — generates test suite (once, at start)
│   │   ├── code_validator_agent.py # port 8015 — pylint + radon validation
│   │   ├── comm_logger_agent.py    # port 8016 — logs all peer messages to JSONL
│   │   └── metrics_tracker_agent.py# port 8017 — tracks per-round metrics to JSONL
│   ├── tools/
│   │   └── executor.py             # run_python() function — not an agent
│   ├── shared/                     # copied from collab_boss_worker/shared/
│   ├── logs/                       # round_table_*.jsonl + sessions.log
│   ├── orchestrator.py             # LangGraph graph (metadata only, no message content)
│   ├── logger_rt.py                # Round Table logger (separate from shared/logger.py)
│   ├── run_round_table.py          # Starts all 8 agents + runs orchestrator
│   └── test_round_table.py         # End-to-end test — LCS task
└── requirements.txt
```

## Key Design Decisions
- **Single model** (`gemini-2.5-flash-lite`) used by all agents — free tier, 20 RPD limit
- **`X-Sender` header** passed on every inter-agent HTTP call so `base_agent.py` can log who sent what
- **Reviewer JSON parsing** strips markdown code fences before `json.loads()` — Gemini often wraps responses in ` ```json ``` `
- **Retry loop** in Boss: up to `MAX_RETRIES = 2` coder retries on failed reviews; feedback (issues + suggestions) is passed back to Coder each time
- **`.env` file** in `a2a_system/` loaded via `python-dotenv` — never hardcode the API key

## Logging
Every inter-agent handoff is logged with:
- Sender → Receiver + skill name
- Full payload content (in `session.log`)
- Character counts
- Timing per call (ms)
- Review verdict + issues/suggestions

Log functions in `shared/logger.py`: `log_send`, `log_receive`, `log_reply`, `log_verdict`, `log_gemini`

## Running the System

**Boss-Worker scenario:**
```bash
cd collab_boss_worker
python3 run_all.py          # starts all 4 agents (ports 8000-8003)
# in another terminal:
python3 test_task.py        # runs the end-to-end test
```

**Round Table scenario:**
```bash
cd collab_round_table
python3 run_round_table.py          # starts all 8 agents + runs orchestrator
# or, if agents already running, in another terminal:
python3 test_round_table.py         # runs the LCS end-to-end test
```

## Rate Limits (Free Tier)
- `gemini-2.5-flash-lite`: 20 requests/day
- Each full pipeline run uses ~4 requests minimum (decompose + plan + code + review)
- If reviewer returns `"fail"`, each retry costs 2 more requests (code + review)
- To avoid hitting the limit: fix bugs that cause unnecessary retries before running

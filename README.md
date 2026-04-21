# AgentTeam — Multi-Agent A2A System

A fully A2A-compliant multi-agent system where a **Boss Agent** autonomously orchestrates a pipeline of three worker agents to solve coding tasks end-to-end. Built with FastAPI + Google Gemini (`gemini-2.5-flash-lite`).

---

## Architecture

```
Client
  └─► BossAgent (port 8000)          ← Gemini function-calling loop
        ├─► PlannerAgent  (port 8001) ← think → act (2-turn)
        ├─► CoderAgent    (port 8002) ← true agent: write → run → self-correct
        └─► ReviewerAgent (port 8003) ← think → act (2-turn)
```

### Pipeline Flow
1. **Boss** receives a coding task and enters a Gemini function-calling loop
2. **Boss → Planner** — gets a numbered step-by-step technical plan
3. **Boss → Coder** — gets working, self-tested Python code
4. **Boss → Reviewer** — gets a structured JSON pass/fail verdict
5. If verdict is `"fail"`, Boss retries Coder with reviewer feedback (max 3 attempts)
6. Final code + review returned to client

---

## True Agents — What Makes Them Agents

| Agent | Mechanism |
|---|---|
| **Boss** | Gemini function-calling loop — autonomously decides which worker to call and when to finish |
| **Planner** | 2-turn think→act — reasons about challenges before producing a plan |
| **Coder** | Full ReAct loop — writes code, executes it via `run_python`, observes output, self-corrects |
| **Reviewer** | 2-turn think→act — reasons about code quality before issuing a verdict |

---

## A2A Protocol Compliance

All agents implement the [A2A open protocol](https://google.github.io/A2A/):

| Endpoint | Description |
|---|---|
| `GET /.well-known/agent.json` | Agent discovery card |
| `POST /tasks/send` | Synchronous task execution |
| `POST /tasks/sendSubscribe` | SSE streaming task execution |
| `GET /tasks/{task_id}` | Poll task status |
| `POST /tasks/{task_id}/cancel` | Cancel in-flight task |

**Task lifecycle states:** `submitted` → `working` → `completed` / `failed` / `cancelled`

**Message format:** `Message { role, parts: [TextPart | DataPart] }`

---

## File Structure

```
AgentTeam/
├── README.md
├── CLAUDE.md                    # Architecture doc for Claude Code
└── a2a_system/
    ├── agents/
    │   ├── boss_agent.py        # Orchestrator — port 8000
    │   ├── planner_agent.py     # Technical planner — port 8001
    │   ├── coder_agent.py       # Self-correcting coder — port 8002
    │   └── reviewer_agent.py    # Pass/fail reviewer — port 8003
    ├── shared/
    │   ├── base_agent.py        # FastAPI A2A wrapper (all 5 endpoints + SSE)
    │   ├── models.py            # Pydantic A2A models (Task, Message, Part, Artifact, AgentCard)
    │   └── logger.py            # Structured inter-agent handoff logger
    ├── logs/
    │   └── session.log          # Full log: payloads, timings, verdicts
    ├── run_all.py               # Starts all 4 agents concurrently
    ├── test_task.py             # End-to-end test client (sync + SSE streaming)
    ├── requirements.txt
    └── .env                     # GEMINI_API_KEY (gitignored)
```

---

## Setup

### 1. Install dependencies
```bash
cd a2a_system
pip install -r requirements.txt
```

### 2. Add your Gemini API key
Create `a2a_system/.env`:
```
GEMINI_API_KEY=your_key_here
```
Get a free key at [aistudio.google.com](https://aistudio.google.com).

### 3. Start all agents
```bash
python run_all.py
```
This starts Boss (8000), Planner (8001), Coder (8002), and Reviewer (8003) with color-coded output per agent.

---

## Running a Task

```bash
# Synchronous — waits for full result
python test_task.py

# SSE streaming — prints live status updates as the pipeline runs
python test_task.py --stream
```

### Example output
```
──────────────────────────────────────────────────────────────────────
  Sending task to Boss Agent  [sync /tasks/send]
  Task : Write a Python function that merges two sorted lists
  ID   : a3f1c2d4-...

──────────────────────────────────────────────────────────────────────
  Boss Agent Response
  Task ID : a3f1c2d4-...
  State   : completed

──────────────────────────────────────────────────────────────────────
  Artifact: implementation

  def merge_sorted_lists(list1: list[int], list2: list[int]) -> list[int]:
      """Merge two sorted lists into a single sorted list."""
      ...

──────────────────────────────────────────────────────────────────────
  Artifact: review

  {
    "verdict": "pass",
    "summary": "Code is correct, handles edge cases, uses type hints and docstrings.",
    "issues": [],
    "suggestions": ["Consider adding a note about time complexity O(n+m)."]
  }
```

---

## Logging

Every inter-agent handoff is logged to console and `logs/session.log`:

```
[BossAgent → PlannerAgent]  task=abc-plan  skill='plan'
[PlannerAgent → BossAgent]  task=abc-plan  state=completed  artifact=technical_plan  (1823ms)
[BossAgent → CoderAgent]    task=abc-code  skill='code'
  CoderAgent  run_python (step 1)  Executing 342 chars...
  CoderAgent  run_python result    STDOUT: [1, 2, 3, 4, 5]
[CoderAgent → BossAgent]    task=abc-code  state=completed  artifact=implementation  (8441ms)
[VERDICT] pass  |  issues=0  |  suggestions=1
```

---

## Rate Limits

Using `gemini-2.5-flash-lite` free tier (20 requests/day):

| Scenario | Gemini API calls |
|---|---|
| Happy path (review passes first try) | ~10 calls |
| 1 retry (review fails once) | ~16 calls |
| Worst case (3 coder attempts) | ~22 calls |

---

## Model

All agents use `gemini-2.5-flash-lite` — configured in each agent file via `MODEL = "gemini-2.5-flash-lite"`.

# Switching Between Groq and Ollama

Since both setups use the same function signatures, switching is just an import change.

## Quick Switch Guide

### To Use Groq (Default)

Edit these 4 files:
- `a2a_system/collab/collab_boss_worker/agents/boss_agent.py`
- `a2a_system/collab/collab_boss_worker/agents/planner_agent.py`
- `a2a_system/collab/collab_boss_worker/agents/coder_agent.py`
- `a2a_system/collab/collab_boss_worker/agents/reviewer_agent.py`

Change to:
```python
from groq_setup.infer import groq_chat, get_tool_call, tool_result_message
```

**Requirements:**
- Groq API keys in `groq_setup/.env`
- Free tier: 20 requests/day per key
- Requires internet (cloud API)

---

### To Use Ollama (Local)

Edit the same 4 files and change to:
```python
from ollama_setup.infer import groq_chat, get_tool_call, tool_result_message
```

**Requirements:**
- `ollama serve` running on `localhost:11434`
- Mistral model pulled: `ollama pull mistral`
- ~4GB VRAM (GPU recommended but CPU works)
- No internet required (local inference)

---

## When to Use Each

| Aspect | Groq | Ollama |
|--------|------|--------|
| **Speed** | Fast (cloud GPU) | Medium (depends on local GPU) |
| **Cost** | Free (limited quota) | Free (unlimited) |
| **Quota** | 20 requests/day per key | Unlimited |
| **Setup** | API keys | Local install |
| **Internet** | Required | Not required |
| **Best for** | Quick testing, small batches | Extended testing, benchmarks |

---

## Example: Testing Both

```bash
# Test with Groq (when quota available)
cd a2a_system/collab/collab_boss_worker
python3 test_task.py  # Uses groq_setup by default

# Switch to Ollama for more testing
# [Edit 4 files to use ollama_setup]
python3 test_task.py  # Uses ollama_setup (unlimited)

# Switch back to Groq (when quota resets next day)
# [Edit 4 files back to groq_setup]
python3 test_task.py  # Uses groq_setup again
```

---

## File Structure

```
AgentTeam/
├── groq_setup/              # Cloud API (Groq)
│   ├── .env                 # API keys
│   ├── infer.py             # groq_chat(), groq_complete(), etc.
│   └── key_manager.py       # Auto-rotation on rate limit
│
├── ollama_setup/            # Local inference (Ollama)
│   ├── .env                 # Config (localhost:11434)
│   └── infer.py             # Same API as groq_setup
│
├── a2a_system/
│   └── collab/
│       └── collab_boss_worker/
│           ├── agents/
│           │   ├── boss_agent.py      # [EDIT: change import]
│           │   ├── planner_agent.py   # [EDIT: change import]
│           │   ├── coder_agent.py     # [EDIT: change import]
│           │   └── reviewer_agent.py  # [EDIT: change import]
│           └── test_task.py
```

---

## Side-by-Side Import Comparison

### Current (Groq)
```python
# In boss_agent.py, planner_agent.py, coder_agent.py, reviewer_agent.py
from groq_setup.infer import groq_chat, get_tool_call, tool_result_message
```

### Alternative (Ollama)
```python
# In the same files, change to:
from ollama_setup.infer import groq_chat, get_tool_call, tool_result_message
```

**No other code changes needed** — the function signatures are identical.

---

## Verification

After switching, verify it's working:

```bash
# For Groq
python3 test_ollama.py  # Won't apply, skip

# For Ollama
python3 test_ollama.py  # Run to verify setup
python3 test_task.py    # Should work with local inference
```

---

## Notes

- Both setups have the same `groq_chat()`, `groq_complete()`, `get_tool_call()`, `tool_result_message()` function signatures
- No changes needed to agent logic—just swap the import
- The function names deliberately kept the "groq_" prefix for backward compatibility
- All other code (agent logic, API endpoints, orchestration) remains unchanged

# Using Local Ollama on Kaggle GPU

This guide shows how to run the A2A system with **Mistral 7B** locally on Kaggle instead of using the Groq API.

## Setup Steps

### 1. Create a Kaggle Notebook
- Go to [kaggle.com/notebooks](https://kaggle.com/notebooks)
- Create a new notebook
- **Enable GPU** (Accelerator dropdown → GPU, at least T4)

### 2. Install Ollama (Automated Script)

Copy-paste this into a Kaggle notebook cell:

```python
# Cell 1: Install and setup Ollama
!pip install -q httpx  # Required for testing

# Copy the setup script content or run it:
setup_code = """
import subprocess, time, sys, os

def run_cmd(cmd, desc="", timeout=300):
    print(f"\\n→ {desc}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        if result.stdout: print(result.stdout)
        return result.returncode == 0
    except Exception as e:
        print(f"✗ {e}")
        return False

# Install zstd (required by Ollama)
run_cmd("apt-get update && apt-get install -y zstd", "Installing zstd", 60)

# Install Ollama
run_cmd("curl -fsSL https://ollama.ai/install.sh | sh", "Installing Ollama", 120)

# Start server in background
subprocess.Popen("nohup ollama serve > /tmp/ollama.log 2>&1 &", shell=True)

# Wait for server
print("Waiting for Ollama (30s)...")
for i in range(30):
    time.sleep(1)
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            print("✓ Ollama server started!")
            break
    except: pass

# Pull model (~4GB, takes 2-5 min)
print("\\nPulling Mistral 7B (~4GB, 2-5 minutes)...")
run_cmd("ollama pull mistral", "Downloading model", 600)

print("\\n✓ Setup complete!")
"""

exec(setup_code)
```

**What this does:**
- ✓ Installs Ollama binary
- ✓ Starts Ollama server on `localhost:11434`
- ✓ Downloads Mistral 7B model (~4GB)
- ✓ Waits for server to be ready

### 3. Clone/Download AgentTeam and Configure

```python
# Cell 2: Clone the repo
!git clone https://github.com/YOUR_REPO/AgentTeam.git
%cd AgentTeam

# Cell 3: Install dependencies
!pip install -q fastapi uvicorn httpx pydantic python-dotenv

# Cell 4: Verify Ollama is running
import httpx
try:
    resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
    models = resp.json().get("models", [])
    print("✓ Ollama is running")
    print(f"Models: {[m['name'] for m in models]}")
except Exception as e:
    print(f"✗ Ollama not responding: {e}")
```

### 4. Switch Agents to Use Ollama

Edit 4 files in `a2a_system/collab/collab_boss_worker/agents/`:
- `boss_agent.py`
- `planner_agent.py`
- `coder_agent.py`
- `reviewer_agent.py`

**In each file**, find this line:
```python
from groq_setup.infer import groq_chat, get_tool_call, tool_result_message
```

Replace with:
```python
from ollama_setup.infer import groq_chat, get_tool_call, tool_result_message
```

**That's it!** Same function signatures, no other changes needed.

### 5. Run the System in Kaggle

```python
# Cell 5: Start the agents
%cd /kaggle/working/AgentTeam/a2a_system/collab/collab_boss_worker

# Start all 4 agents
!python3 -m uvicorn agents.boss_agent:app --host 127.0.0.1 --port 8000 --no-access-log > /tmp/boss.log 2>&1 &
!python3 -m uvicorn agents.planner_agent:app --host 127.0.0.1 --port 8001 --no-access-log > /tmp/planner.log 2>&1 &
!python3 -m uvicorn agents.coder_agent:app --host 127.0.0.1 --port 8002 --no-access-log > /tmp/coder.log 2>&1 &
!python3 -m uvicorn agents.reviewer_agent:app --host 127.0.0.1 --port 8003 --no-access-log > /tmp/reviewer.log 2>&1 &

import time
time.sleep(6)
print("✓ All agents started")

# Cell 6: Run a test task
!python3 test_task.py
```

**Expected output:**
```
──────────────────────────────────────────────────────────────────────
  Sending task to Boss Agent
──────────────────────────────────────────────────────────────────────
  Task : Write a Python function that merges two sorted lists
  ...
  State   : completed
  ...
```

## Switching Back to Groq

When the Groq quota resets:

1. Change the import back in each agent:
   ```python
   from groq_setup.infer import groq_chat, get_tool_call, tool_result_message
   ```

2. Restart the agents

That's it—no other changes needed.

## Performance Notes

- **Mistral 7B**: ~5-30s per inference depending on GPU and prompt length
- **Kaggle GPU** (Tesla T4): ~15-20s per task
- **Local GPU** (RTX 3090): ~2-5s per task
- No rate limits, unlimited usage

## Troubleshooting

**"Ollama API error" / "Connection refused"**
```python
# Check if Ollama is running:
!curl http://localhost:11434/api/tags

# If not, restart it:
!pkill ollama
!nohup ollama serve > /tmp/ollama.log 2>&1 &
import time; time.sleep(5)

# Check logs:
!tail -20 /tmp/ollama.log
```

**"CUDA out of memory"**
- Mistral 7B needs ~4GB VRAM (Kaggle T4 has 16GB, should be fine)
- If you hit OOM, reduce `max_tokens` in system prompts (currently 2048)
- Or use smaller model: `!ollama pull neural-chat` (5B, ~2GB)

**Slow inference on T4 GPU**
- Mistral 7B: ~15-20s per task on T4
- This is normal—T4 is slower than newer GPUs
- If too slow, switch to `neural-chat` (5B model, faster)

**Model didn't download**
```python
# Check available models:
!ollama list

# If mistral not listed, pull again:
!ollama pull mistral

# Check for disk space (model is ~4GB):
!df -h
```

**Kaggle notebook restarted / Lost Ollama**
- Ollama process stops when the kernel restarts
- Re-run Cell 1 (the setup script) to restart Ollama
- Model stays cached, so pull is fast the second time

## File Structure

```
ollama_setup/
├── __init__.py
├── infer.py          # Same API as groq_setup/infer.py
└── .env              # Config (Ollama runs on localhost:11434)
```

No key manager needed—Ollama handles everything locally.

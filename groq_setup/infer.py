"""
infer.py — Ollama LLM backend with automatic key rotation.

Provides two functions:
  generate(prompt)            — single-turn code generation
  groq_chat(messages, ...)    — multi-turn chat with optional tool calling
  groq_complete(messages, ...) — multi-turn text chat (no tools)

Usage (standalone):
  python3 infer.py "write a binary search function in Python"
"""
import sys
import json
import httpx
try:
    from .key_manager import manager   # when imported as a package
except ImportError:
    from key_manager import manager    # when run directly (python3 infer.py)

MODEL   = "llama2"
API_URL = "http://localhost:11434/v1/chat/completions"

CODE_SYSTEM = """\
You are an expert software engineer. When asked to write code:
- Write clean, well-structured code
- Include docstrings and type hints
- Add brief inline comments for non-obvious logic
- Include example usage or test cases at the bottom
- Output only the code, no extra explanation unless asked"""


# ── Core API call ─────────────────────────────────────────────────────────────

def _post(api_key: str, payload: dict) -> dict:
    """POST to Ollama and return the assistant message dict."""
    # Ollama runs locally, no authentication needed
    resp = httpx.post(
        API_URL,
        json=payload,
        timeout=120,
    )
    if resp.status_code != 200:
        raise Exception(f"{resp.status_code} {resp.text}")
    return resp.json()["choices"][0]["message"]


# ── Public API ────────────────────────────────────────────────────────────────

def generate(prompt: str, system: str = CODE_SYSTEM, max_tokens: int = 2048) -> str:
    """
    Single-turn text generation. Returns the response string.
    Automatically rotates keys on rate limits.
    """
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    msg = manager.call_with_rotation(_post, payload)
    return msg.get("content") or ""


def groq_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    system: str | None = None,
    tool_choice: str = "required",
    max_tokens: int = 2048,
) -> dict:
    """
    Multi-turn chat completion with optional tool calling.

    Args:
        messages:    OpenAI-format message list (role/content/tool_calls).
        tools:       OpenAI-format tool list. If None, no tool calling.
        system:      System prompt string (prepended automatically).
        tool_choice: "required" forces a tool call; "auto" lets model decide.
        max_tokens:  Maximum tokens to generate.

    Returns:
        The assistant message dict (role, content, tool_calls).
        Access tool calls via: msg["tool_calls"][0]["function"]["name/arguments"]
    """
    all_messages = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend(messages)

    payload: dict = {
        "model": MODEL,
        "messages": all_messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    return manager.call_with_rotation(_post, payload)


def groq_complete(
    messages: list[dict],
    system: str | None = None,
    max_tokens: int = 2048,
) -> str:
    """
    Multi-turn text conversation without tool calling. Returns response string.
    Use this for think→act style 2-turn reasoning patterns.
    """
    msg = groq_chat(messages, tools=None, system=system, max_tokens=max_tokens)
    return msg.get("content") or ""


def get_tool_call(msg: dict) -> tuple[str, dict, str] | None:
    """
    Extract the first tool call from an assistant message.

    Returns:
        (name, args_dict, tool_call_id) or None if no tool call.
    """
    tool_calls = msg.get("tool_calls") or []
    if not tool_calls:
        return None
    tc = tool_calls[0]
    name = tc["function"]["name"]
    try:
        args = json.loads(tc["function"]["arguments"])
    except (json.JSONDecodeError, KeyError):
        args = {}
    return name, args, tc["id"]


def tool_result_message(tool_call_id: str, result: str) -> dict:
    """Build the tool result message to append to conversation history."""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": str(result)}


# ── Standalone CLI ────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        print("Enter your code generation prompt (Ctrl+D to submit):")
        prompt = sys.stdin.read().strip()

    if not prompt:
        print("No prompt provided.")
        return

    print(f"\n[infer] Model : {MODEL}")
    print(f"[infer] Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}\n")
    print("=" * 60)
    print(generate(prompt))
    print("=" * 60)


if __name__ == "__main__":
    main()

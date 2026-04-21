"""
infer.py — Local Ollama inference (drop-in replacement for groq_setup/infer.py).

Same function signatures as groq_setup so you can swap imports:
  from ollama_setup.infer import groq_chat, groq_complete, generate, get_tool_call, tool_result_message

Requires: Ollama running locally on http://localhost:11434
Model: mistral (7B, ~4GB VRAM, good quality/speed tradeoff for Kaggle GPU)

Setup:
  1. In Kaggle notebook: !curl https://ollama.ai/install.sh | sh
  2. ollama pull mistral
  3. ollama serve (in background)
  4. Use this module
"""
import json
import httpx

OLLAMA_API = "http://localhost:11434/api/chat"
MODEL = "mistral"

# Keep same system prompt as original groq_setup
CODE_SYSTEM = """\
You are an expert software engineer. When asked to write code:
- Write clean, well-structured code
- Include docstrings and type hints
- Add brief inline comments for non-obvious logic
- Include example usage or test cases at the bottom
- Output only the code, no extra explanation unless asked"""


def groq_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    system: str | None = None,
    tool_choice: str = "required",
    max_tokens: int = 2048,
) -> dict:
    """
    Multi-turn chat completion with optional tool calling.
    Compatible with groq_setup.groq_chat() signature.

    Args:
        messages:    OpenAI-format message list (role/content/tool_calls).
        tools:       OpenAI-format tool list (passed but Ollama may not use them).
        system:      System prompt string.
        tool_choice: Ignored (Ollama doesn't enforce tool_choice).
        max_tokens:  Maximum tokens to generate.

    Returns:
        The assistant message dict (role, content, tool_calls).
    """
    all_messages = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend(messages)

    payload = {
        "model": MODEL,
        "messages": all_messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.0,
        },
    }

    try:
        resp = httpx.post(OLLAMA_API, json=payload, timeout=300.0)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Ollama API error: {e}")

    data = resp.json()
    msg = {"role": "assistant", "content": data.get("message", {}).get("content", "")}

    # If tools were provided and the response looks like tool calls, try to parse
    # Note: Mistral 7B doesn't natively support tool calling, but we can prompt for it
    if tools and "tool_calls" in data.get("message", {}):
        msg["tool_calls"] = data["message"]["tool_calls"]

    return msg


def groq_complete(
    messages: list[dict],
    system: str | None = None,
    max_tokens: int = 2048,
) -> str:
    """
    Multi-turn text conversation without tool calling. Returns response string.
    Compatible with groq_setup.groq_complete() signature.
    """
    msg = groq_chat(messages, tools=None, system=system, max_tokens=max_tokens)
    return msg.get("content") or ""


def generate(prompt: str, system: str = CODE_SYSTEM, max_tokens: int = 2048) -> str:
    """
    Single-turn text generation. Returns the response string.
    Compatible with groq_setup.generate() signature.
    """
    messages = [{"role": "user", "content": prompt}]
    return groq_complete(messages, system=system, max_tokens=max_tokens)


def get_tool_call(msg: dict) -> tuple[str, dict, str] | None:
    """
    Extract the first tool call from an assistant message.
    Compatible with groq_setup.get_tool_call() signature.

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

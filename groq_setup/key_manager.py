"""
key_manager.py — Round-robin Groq API key rotator.

Automatically rotates to the next key on 429 (rate limit) or 401 (invalid key).
By the time all keys are cycled through, the first key's rate window has usually reset.
"""
import os
import random
import time
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def _load_keys() -> list[str]:
    keys = []
    i = 1
    while True:
        key = os.getenv(f"GROQ_KEY_{i}")
        if not key:
            break
        keys.append(key.strip())
        i += 1
    if not keys:
        raise ValueError("No GROQ_KEY_1, GROQ_KEY_2... found in .env")
    return keys


class KeyManager:
    def __init__(self):
        self._keys = _load_keys()
        self._index = 0
        print(f"[KeyManager] Loaded {len(self._keys)} key(s)")

    @property
    def current_key(self) -> str:
        return self._keys[self._index]

    def rotate(self) -> str:
        self._index = (self._index + 1) % len(self._keys)
        print(f"[KeyManager] Rotated to key {self._index + 1}")
        return self._keys[self._index]

    def call_with_rotation(self, fn, *args, max_retries: int = None, **kwargs):
        """
        Call fn(api_key, *args, **kwargs).
        On 429 or auth error: rotate key and retry.
        Cycles through all keys up to max_retries times total.
        """
        if max_retries is None:
            max_retries = len(self._keys) * 10  # 10 full cycles max (~600s)

        last_error = None
        for attempt in range(max_retries):
            try:
                return fn(self.current_key, *args, **kwargs)
            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower():
                    completed_cycles = attempt // len(self._keys)
                    position_in_cycle = attempt % len(self._keys)
                    is_last_in_cycle = position_in_cycle == len(self._keys) - 1
                    if is_last_in_cycle:
                        # Exponential backoff per cycle + jitter so concurrent agents
                        # don't all wake up and hammer the API at the same moment.
                        base = min(60 + completed_cycles * 30, 300)
                        wait = base + random.uniform(0, 20)
                    else:
                        wait = 3
                    print(f"[KeyManager] Rate limit on key {self._index + 1} "
                          f"(cycle {completed_cycles + 1}, wait {wait:.0f}s), rotating...")
                    self.rotate()
                    time.sleep(wait)
                elif "401" in err or "invalid_api_key" in err.lower():
                    print(f"[KeyManager] Invalid key {self._index + 1}, rotating...")
                    self.rotate()
                else:
                    raise  # non-quota error — don't retry
                last_error = e

        raise RuntimeError(f"All keys exhausted after {max_retries} attempts. Last error: {last_error}")


# Singleton — import and use directly
manager = KeyManager()

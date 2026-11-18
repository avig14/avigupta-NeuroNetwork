"""Thin Groq wrapper for the gate's optional LLM parts (L3 judge, LLM text-only baseline).

Docs-first (checked 18 Nov 2026, console.groq.com/docs): OpenAI-compatible chat completions,
strict `json_schema` structured output, `reasoning_effort` for gpt-oss, rate limits from x-ratelimit-* headers.
  - The key comes from GROQ_API_KEY (environment or a gitignored .env). It is NEVER passed in code, logged,
    or written to evidence packs.
  - Only synthetic fleet data is ever sent. No user name, email or machine details.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any

# $ per 1M tokens (input, output). Groq pricing page, 18 Nov 2026. Estimate only.
PRICES = {"openai/gpt-oss-120b": (0.15, 0.60), "openai/gpt-oss-20b": (0.075, 0.30),
          "qwen/qwen3.8-27b": (0.80, 4.00)}
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT = "openai/gpt-oss-120b"


class LLMUnavailable(RuntimeError):
    """GROQ_API_KEY is not set."""


class LLMRefused(RuntimeError):
    """The model declined (stop_reason == 'refusal') or returned unusable output."""


@dataclass
class Meter:
    """Process-wide token meter. Real numbers from `response.usage`, not estimates."""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_model: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, usage: Any) -> None:
        i = int(getattr(usage, "input_tokens", 0) or 0)
        o = int(getattr(usage, "output_tokens", 0) or 0)
        with self._lock:
            self.calls += 1
            self.input_tokens += i
            self.output_tokens += o
            m = self.by_model.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            m["calls"] += 1
            m["input_tokens"] += i
            m["output_tokens"] += o

    def snapshot(self) -> dict:
        with self._lock:
            usd = sum(v["input_tokens"] * PRICES.get(k, (0, 0))[0] / 1e6 +
                      v["output_tokens"] * PRICES.get(k, (0, 0))[1] / 1e6 for k, v in self.by_model.items())
            return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                    "by_model": json.loads(json.dumps(self.by_model)), "est_usd": round(usd, 4)}

    def reset(self) -> None:
        with self._lock:
            self.calls = self.input_tokens = self.output_tokens = 0
            self.by_model = {}


METER = Meter()


def llm_available(model: str | None = None) -> bool:
    """True when GROQ_API_KEY is present."""
    return bool(os.environ.get("GROQ_API_KEY"))


def default_model() -> str:
    """ARG_LLM_MODEL wins, else openai/gpt-oss-120b."""
    return os.environ.get("ARG_LLM_MODEL") or GROQ_DEFAULT


def load_dotenv(path: str = ".env") -> bool:
    """Load KEY=VALUE lines from a gitignored .env into os.environ (never overrides). No echo."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        return True
    except OSError:
        return False


async def complete_json(system: str, user: str, schema: dict, *, model: str | None = None,
                        effort: str = "medium", max_tokens: int = 8000) -> dict:
    """One structured-output call. Returns the parsed JSON dict. Raises LLMRefused on refusal or bad output.
    `effort` is kept for callers; Groq reasoning effort is set inside `_groq_json`."""
    return await _groq_json(system, user, schema, model or default_model(), max_tokens)


_groq = None
_groq_lock = None
_groq_next_ok = 0.0   # monotonic time before which the token bucket is (probably) empty


def _parse_dur(txt: str) -> float:
    """'51.63s', '1m2.5s', '1h19m12s' -> seconds."""
    import re
    tot = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", txt or ""):
        tot += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return tot


async def _groq_json(system: str, user: str, schema: dict, model: str, max_tokens: int) -> dict:
    """Groq, OpenAI-compatible chat completions, strict json_schema (docs: console.groq.com/docs/structured-outputs).

    Plan limits for gpt-oss (console.groq.com/docs/rate-limits, 18 Nov 2026): 30 req/min, 1K req/day, 8K tokens/min,
    200K tokens/day. So calls are SERIALISED and paced from the x-ratelimit-* response headers; a 429 honours
    `retry-after`; a wait over 90s (daily budget gone) raises instead of hanging. Key from GROQ_API_KEY only, never logged.
    """
    import asyncio
    import time

    import httpx
    global _groq, _groq_lock, _groq_next_ok
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMUnavailable("GROQ_API_KEY not set. Put it in the environment or a gitignored .env file.")
    if _groq is None:
        _groq = httpx.AsyncClient(timeout=120.0)
        _groq_lock = asyncio.Lock()
    body = {"model": model, "max_tokens": max_tokens, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "verdict", "strict": True, "schema": schema}}}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"      # documented: low|medium|high (console.groq.com/docs/reasoning)
        body["include_reasoning"] = False
    async with _groq_lock:
        data = None
        for attempt in range(5):
            gap = _groq_next_ok - time.monotonic()
            if gap > 0:
                await asyncio.sleep(gap)
            r = await _groq.post(GROQ_URL, json=body, headers={"Authorization": f"Bearer {key}"})
            rem = r.headers.get("x-ratelimit-remaining-tokens")
            if rem is not None and int(rem) < 2500:      # next call would not fit: wait for the bucket
                _groq_next_ok = time.monotonic() + _parse_dur(r.headers.get("x-ratelimit-reset-tokens", "")) + 0.5
            if r.status_code == 429:
                wait = float(r.headers.get("retry-after", "0") or 0) or 10.0
                if wait > 90:
                    raise LLMRefused(f"groq daily limit reached (retry-after {int(wait)}s)")
                _groq_next_ok = time.monotonic() + wait + 0.5
                continue
            if r.status_code in (500, 502, 503, 504):
                _groq_next_ok = time.monotonic() + 2 ** attempt
                continue
            if r.status_code != 200:
                raise LLMRefused(f"groq HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            break
        if data is None:
            raise LLMRefused("groq: retries exhausted (rate limit)")
    u = data.get("usage", {})

    class _U:
        input_tokens = u.get("prompt_tokens", 0)
        output_tokens = u.get("completion_tokens", 0)
    METER.add(model, _U())
    ch = (data.get("choices") or [{}])[0]
    if ch.get("finish_reason") == "length":
        raise LLMRefused("model hit max_tokens before finishing")
    msg = ch.get("message") or {}
    if msg.get("refusal"):
        raise LLMRefused(f"model refused: {str(msg['refusal'])[:100]}")
    try:
        return json.loads(msg.get("content") or "")
    except json.JSONDecodeError as exc:
        raise LLMRefused(f"unparseable model output: {exc}") from exc

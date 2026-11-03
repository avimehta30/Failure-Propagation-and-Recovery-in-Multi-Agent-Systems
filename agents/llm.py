"""Model calls through any OpenAI-compatible API (the UCSD TritonAI gateway by default), with a response cache.

The cache key is (model, messages, seed, temperature, max_tokens). A cache hit returns the
original reply together with its original token counts and latency, so rerunning an
experiment costs nothing and reports the same cost as the first run.

Prompts can contain absolute paths (e.g. a script's traceback names its workspace file). So that
the cache works in any clone, the key is computed with this clone's path replaced by CACHE_ROOT,
the path of the machine the cache was first built on. The model still sees the real prompt.

The API key and base URL come from environment variables or the project's .env file. The key
is never logged, cached or printed. Reasoning models' hidden reasoning text is kept separately
from the answer, cached, and logged to the trace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "runs" / ".llm_cache"
CACHE_ROOT = "/Users/avimehta/Failure-Propagation-and-Recovery-in-Multi-Agent-Systems"


class RateLimitExhausted(RuntimeError):
    """The provider's quota is used up for longer than we are willing to wait. Rerun later."""


@dataclass
class LLMReply:
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cached: bool = False
    reasoning: str = ""


def load_env(names, env_file: Path = ROOT / ".env") -> str:
    """The first of `names` that is set in the environment or in .env."""
    for name in names:
        if os.environ.get(name):
            return os.environ[name].strip()
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m and m.group(1) in names and m.group(2):
                return m.group(2).strip().strip("'\"")
    raise RuntimeError(f"not set: one of {names} in the environment or in .env")


def load_api_key(names=("OPENAI_API_KEY",), env_file: Path = ROOT / ".env") -> str:
    return load_env(names, env_file)


class LLM:
    def __init__(self, model: str = "api-glm-5.3-flash", base_url: str | None = None,
                 base_url_env=("OPENAI_BASE_URL",), api_key_env=("OPENAI_API_KEY",), temperature: float = 0.0,
                 max_tokens: int = 4000, json_mode: bool = True, cache_dir: Path | str | None = DEFAULT_CACHE,
                 timeout_s: int = 180, max_wait_s: int = 900):
        self.model = model
        # The URL and key are read on the first real call, so cached replays need no .env.
        self.base_url = base_url.rstrip("/") if base_url else None
        self.base_url_env = tuple(base_url_env)
        self.api_key_env = tuple(api_key_env)
        self.temperature, self.max_tokens, self.json_mode = temperature, max_tokens, json_mode
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout_s, self.max_wait_s = timeout_s, max_wait_s
        self._key: str | None = None

    def chat(self, messages: list[dict], *, seed: int = 0, max_tokens: int | None = None) -> LLMReply:
        max_tokens = max_tokens or self.max_tokens
        keyed = json.dumps([self.model, messages, seed, self.temperature, max_tokens], sort_keys=True)
        key = hashlib.sha256(keyed.replace(str(ROOT), CACHE_ROOT).encode()).hexdigest()
        cached = self._cache_get(key)
        if cached:
            return LLMReply(cached["text"], cached["tokens_in"], cached["tokens_out"], cached["latency_ms"], True,
                            cached.get("reasoning", ""))
        reply = self._call(messages, seed, max_tokens)
        self._cache_put(key, reply)
        return reply

    # ---------------------------------------------------------------- provider call
    def _call(self, messages, seed, max_tokens) -> LLMReply:
        if self.base_url is None:
            self.base_url = load_env(self.base_url_env).rstrip("/")
        if self._key is None:
            self._key = load_api_key(self.api_key_env)
        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "seed": seed, "max_tokens": max_tokens}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        waited = 0.0
        while True:
            req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {self._key}",
                                                  "Content-Type": "application/json",
                                                  "User-Agent": "lifeline-experiment"})
            start = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                    data = json.load(r)
                latency = (time.perf_counter() - start) * 1000
                usage = data.get("usage", {})
                msg = data["choices"][0]["message"]
                text = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
                return LLMReply(_strip_thinking(text), usage.get("prompt_tokens", 0),
                                usage.get("completion_tokens", 0), latency, reasoning=reasoning)
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                if e.code == 400 and "failed_generation" in detail:
                    # JSON mode rejected the model's output; hand the raw text back so the agent can retry.
                    failed = json.loads(detail).get("error", {}).get("failed_generation", "")
                    return LLMReply(_strip_thinking(failed), 0, 0, (time.perf_counter() - start) * 1000)
                if e.code in (429, 500, 502, 503, 504):
                    wait = _retry_after(e, detail)
                    if waited + wait > self.max_wait_s:
                        raise RateLimitExhausted(f"{e.code}: provider says wait {wait:.0f}s; "
                                                 f"{_short(detail)}") from None
                    time.sleep(wait)
                    waited += wait
                    continue
                raise RuntimeError(f"model API error {e.code}: {_short(detail)}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if waited > self.max_wait_s:
                    raise
                time.sleep(10)
                waited += 10

    # ---------------------------------------------------------------- cache
    def _cache_get(self, key: str) -> dict | None:
        if not self.cache_dir:
            return None
        p = self.cache_dir / key[:2] / f"{key}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def _cache_put(self, key: str, reply: LLMReply) -> None:
        if not self.cache_dir:
            return
        p = self.cache_dir / key[:2] / f"{key}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"model": self.model, "text": reply.text, "tokens_in": reply.tokens_in,
                                 "tokens_out": reply.tokens_out, "latency_ms": round(reply.latency_ms, 1),
                                 "reasoning": reply.reasoning}))


class ScriptedLLM:
    """Offline stand-in for tests: `policy(messages) -> reply text`. Reports fixed small costs."""

    model = "scripted"

    def __init__(self, policy):
        self.policy = policy
        self.calls: list[list[dict]] = []

    def chat(self, messages, *, seed=0, max_tokens=None) -> LLMReply:
        self.calls.append(messages)
        text = self.policy(messages)
        return LLMReply(text, sum(len(m["content"]) for m in messages) // 4, len(text) // 4, 1.0)


def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _retry_after(e: urllib.error.HTTPError, detail: str) -> float:
    header = e.headers.get("retry-after") if e.headers else None
    if header:
        try:
            return float(header) + 1
        except ValueError:
            pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", detail)
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2)) + 1
    return 20.0


def _short(detail: str) -> str:
    try:
        return json.loads(detail)["error"]["message"][:300]
    except Exception:
        return detail[:300]

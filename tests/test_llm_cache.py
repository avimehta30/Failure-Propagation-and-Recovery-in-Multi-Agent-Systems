"""The response cache replays in any clone: no .env needed, and absolute paths in prompts do not
change the cache key."""

from pathlib import Path

import agents.llm as llm_mod
from agents.llm import LLM, LLMReply


def _no_call(*args, **kwargs):
    raise AssertionError("cache miss: the model would have been called")


def test_cache_hit_needs_no_env_and_ignores_clone_path(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    here = str(llm_mod.ROOT)
    prompt = [{"role": "user", "content": f'File "{here}/runs/x/workspace/scripts/a.py", line 3'}]

    first = LLM(cache_dir=tmp_path)
    first._call = lambda messages, seed, max_tokens: LLMReply("ok", 1, 1, 5.0)
    first.chat(prompt)

    # The same run in another clone: its path appears in the prompt instead.
    other = Path("/somewhere/else/clone")
    monkeypatch.setattr(llm_mod, "ROOT", other)
    moved = [{"role": "user", "content": prompt[0]["content"].replace(here, str(other))}]
    second = LLM(cache_dir=tmp_path, base_url=None)
    second._call = _no_call
    reply = second.chat(moved)
    assert reply.cached and reply.text == "ok"

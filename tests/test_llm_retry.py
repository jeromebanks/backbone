"""LLM call retries: a validation failure is fed back to the next attempt (no real LLM is called)."""
from pydantic import BaseModel

import backbone.llm as L


class Out(BaseModel):
    n: int


def test_validation_error_is_fed_back_to_the_retry(monkeypatch):
    prompts = []

    def fake(system, prompt, schema, model, effort, timeout):
        prompts.append(prompt)
        return L.LLMResult(data={"n": "not a number"} if len(prompts) == 1 else {"n": 3}, model=model,
                           input_tokens=0, output_tokens=0, cost_usd=0.0, latency_ms=0)

    monkeypatch.setattr(L, "BACKEND", "claude-cli")
    monkeypatch.setattr(L, "_claude_cli", fake)
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    res = L.complete_json("sys", "PROMPT", Out)
    assert res.data.n == 3 and res.attempts == 2
    assert prompts[0] == "PROMPT"
    assert prompts[1].startswith("PROMPT") and "failed validation" in prompts[1] and "n" in prompts[1]

"""LLM backends. Both return schema-validated JSON plus usage, so callers never parse free text.

BACKBONE_LLM=claude-cli     (default) Claude Code headless (`claude -p`), authenticated by the user's
                            Claude subscription login. Structured output via --json-schema.
BACKBONE_LLM=anthropic-api  Anthropic SDK with ANTHROPIC_API_KEY. Structured output via output_config.format.

The LLM is only used at semantic boundaries: per-document extraction, question -> QueryPlan, and
narrating computed results. It never does arithmetic that feeds an answer.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Type

from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = os.environ.get("BACKBONE_MODEL", "claude-opus-5-5")
BACKEND = os.environ.get("BACKBONE_LLM", "claude-cli")


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: Any
    model: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    attempts: int = 1
    raw: dict = field(default_factory=dict)


_CWD = None


def _neutral_cwd() -> str:
    # Run the CLI outside the repo so no project CLAUDE.md/settings leak into extraction prompts.
    global _CWD
    if _CWD is None:
        _CWD = tempfile.mkdtemp(prefix="backbone-llm-")
    return _CWD


def _claude_cli(system: str, prompt: str, schema: dict, model: str, effort: str, timeout: int) -> LLMResult:
    cmd = [
        "claude", "-p",
        "--model", model,
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", "",
        "--system-prompt", system,
        "--no-session-persistence",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--effort", effort,
    ]
    t0 = time.monotonic()
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=_neutral_cwd())
    latency = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0:
        raise LLMError(f"claude CLI exit {proc.returncode}: {proc.stderr[-500:] or proc.stdout[-500:]}")
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"claude CLI returned non-JSON: {proc.stdout[:300]}") from e
    if env.get("is_error"):
        raise LLMError(f"claude CLI error: {env.get('subtype')} {env.get('result', '')[:300]}")
    data = env.get("structured_output")
    if data is None:
        try:
            data = json.loads(env.get("result", ""))
        except json.JSONDecodeError as e:
            raise LLMError(f"no structured output: {env.get('result', '')[:300]}") from e
    usage = env.get("usage", {})
    return LLMResult(
        data=data,
        model=model,
        latency_ms=latency,
        input_tokens=(usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
                      + usage.get("cache_read_input_tokens", 0)),
        output_tokens=usage.get("output_tokens", 0),
        cost_usd=env.get("total_cost_usd"),
        raw={k: env.get(k) for k in ("session_id", "num_turns", "duration_api_ms", "stop_reason")},
    )


def _anthropic_api(system: str, prompt: str, schema: dict, model: str, effort: str, timeout: int) -> LLMResult:
    import anthropic

    client = anthropic.Anthropic(timeout=timeout)
    t0 = time.monotonic()
    with client.beta.messages.stream(
        model=model,
        max_tokens=32000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    latency = int((time.monotonic() - t0) * 1000)
    if msg.stop_reason == "refusal":
        raise LLMError(f"refused: {getattr(msg, 'stop_details', None)}")
    text = next((b.text for b in msg.content if b.type == "text"), "")
    u = msg.usage
    return LLMResult(
        data=json.loads(text),
        model=msg.model,
        latency_ms=latency,
        input_tokens=(u.input_tokens or 0) + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0),
        output_tokens=u.output_tokens or 0,
        cost_usd=None,
    )


_UNSUPPORTED_KEYWORDS = {"discriminator"}


def _sanitize(schema):
    """Drop JSON-Schema keywords the strict validators reject; Pydantic still validates the full model afterwards."""
    if isinstance(schema, dict):
        return {k: _sanitize(v) for k, v in schema.items() if k not in _UNSUPPORTED_KEYWORDS}
    if isinstance(schema, list):
        return [_sanitize(v) for v in schema]
    return schema


def complete_json(
    system: str,
    prompt: str,
    model_cls: Type[BaseModel],
    *,
    model: str | None = None,
    effort: str = "high",
    timeout: int = 600,
    retries: int = 2,
) -> LLMResult:
    """Call the configured backend and validate against `model_cls`. Retries on transport or validation errors."""
    model = model or DEFAULT_MODEL
    schema = _sanitize(model_cls.model_json_schema())
    fn = _anthropic_api if BACKEND == "anthropic-api" else _claude_cli
    last: Exception | None = None
    attempt_prompt = prompt
    for attempt in range(1, retries + 2):
        try:
            res = fn(system, attempt_prompt, schema, model, effort, timeout)
            res.data = model_cls.model_validate(res.data)
            res.attempts = attempt
            return res
        except (LLMError, ValidationError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            last = e
            if isinstance(e, ValidationError):
                # Re-asking the same prompt tends to repeat the same invalid output (e.g. a QueryPlan option a
                # validator rejects): tell the next attempt what failed. Transport errors are retried unchanged.
                attempt_prompt = (prompt + "\n\nYour previous output failed validation; return corrected JSON that "
                                  "satisfies the schema and these errors:\n" + str(e)[:2000])
            if "not a valid JSON Schema" in str(e):   # deterministic; retrying cannot help
                break
            time.sleep(2 * attempt)
    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last}")

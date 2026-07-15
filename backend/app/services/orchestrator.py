"""LLM orchestrator — one OpenAI-compatible client, per-job model routing.

Design rule: structured output only. Every job returns JSON that is parsed
and Pydantic-validated by the caller; on failure the call is retried once
with the validation error appended.
"""
import json
import logging
import re
import time
from typing import Type, TypeVar

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from ..config import settings
from .model_discovery import ensure_env_models_written, list_model_ids, pick_model_for_job

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

# Gateway timeouts/disconnects are transient more often than not — retry with
# exponential backoff before surfacing the failure to the pipeline.
_TRANSIENT_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError)
_MAX_TRANSIENT_RETRIES = 3
_BACKOFF_BASE_SEC = 2.0

_client: OpenAI | None = None


def _create_with_retry(client: OpenAI, job: str, **kwargs):
    last_exc: Exception | None = None
    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except _TRANSIENT_ERRORS as exc:
            last_exc = exc
            if attempt < _MAX_TRANSIENT_RETRIES:
                delay = _BACKOFF_BASE_SEC * (2**attempt)  # 2s, 4s, 8s
                logger.warning(
                    "LLM job '%s' transient error (attempt %d/%d), retrying in %.0fs: %s",
                    job, attempt + 1, _MAX_TRANSIENT_RETRIES + 1, delay, exc,
                )
                time.sleep(delay)
    raise RuntimeError(
        f"LLM gateway did not respond after {_MAX_TRANSIENT_RETRIES + 1} attempts "
        f"({type(last_exc).__name__}: {last_exc}). Check the gateway or raise LLM_TIMEOUT_SEC."
    ) from last_exc


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.llm_base_url_resolved or not settings.llm_api_key_resolved:
            raise RuntimeError("LLM not configured: set LLM_BASE_URL/LLM_API_KEY (or root base_URL/OPENAI_API_KEY) in env")
        _client = OpenAI(
            base_url=settings.llm_base_url_resolved,
            api_key=settings.llm_api_key_resolved,
            timeout=settings.llm_timeout_sec,
            max_retries=1,  # gateway hangs are common; fail fast, our job-level retry covers it
        )
    return _client


def _model_for_job(job: str) -> str:
    model = {
        "summary": settings.llm_model_summary,
        "minutes": settings.llm_model_summary,  # same routing as summary
        "extract": settings.llm_model_extract,
        "classify": settings.llm_model_classify,
        "plan": settings.llm_model_plan or settings.llm_model_extract,
        "chat": settings.llm_model_chat or settings.llm_model_extract,
        "triage": settings.llm_model_triage or settings.llm_model_extract,
    }.get(job, "")

    if model:
        return model

    # If models aren't configured, discover them from the gateway using the
    # configured base URL + API key, then persist to backend/.env.
    ensure_env_models_written()

    model = {
        "summary": settings.llm_model_summary,
        "extract": settings.llm_model_extract,
        "classify": settings.llm_model_classify,
    }.get(job, "")
    if model:
        return model

    ids = list_model_ids()
    selected = pick_model_for_job(job, ids)
    return selected


def _max_tokens_for_job(job: str) -> int:
    # Budgets sized for reasoning models (gpt-oss): hidden reasoning tokens count
    # against max_tokens (measured ~1300 per extract call), so visible JSON gets
    # truncated if the cap is tight. run_json_job doubles the cap once on truncation.
    return {
        "summary": 3000,
        "minutes": 6000,  # a full Markdown minutes document
        "extract": 6000,
        "classify": 4000,
        "plan": 4000,
        "chat": 4000,
        "triage": 6000,  # one object per task, and 120b reasons before answering
    }.get(job, 4000)


def _extract_json(raw: str) -> dict:
    """Parse a JSON object from raw model output, tolerating fences and prose."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def run_json_job(job: str, system: str, user: str, schema: Type[T]) -> T:
    """Run an LLM job and return validated structured output. One retry on bad JSON."""
    client = _get_client()
    model = _model_for_job(job)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]  # type: ignore[var-annotated]

    extra_body = {}
    # Only reasoning-capable models (gpt-oss family) take the param, and only with
    # valid values (low/medium/high) — the gateway HANGS (0 bytes until timeout)
    # on reasoning_effort="none", and other routes stall or 502 on the param at all.
    if settings.llm_reasoning_effort not in ("", "none") and "gpt-oss" in model:
        extra_body["reasoning_effort"] = settings.llm_reasoning_effort
        # LiteLLM proxies reject non-standard params for some providers unless whitelisted.
        extra_body["allowed_openai_params"] = ["reasoning_effort"]

    last_error: Exception | None = None
    max_tokens = _max_tokens_for_job(job)
    for attempt in range(2):
        resp = _create_with_retry(
            client,
            job,
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        choice = resp.choices[0]
        raw = choice.message.content or ""
        if choice.finish_reason == "length":
            # Truncated mid-JSON — parsing is pointless; retry with more room.
            last_error = ValueError(
                f"output truncated at max_tokens={max_tokens} "
                "(reasoning models spend part of the budget on hidden reasoning)"
            )
            max_tokens *= 2
            continue
        try:
            return schema.model_validate(_extract_json(raw))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            if attempt == 0:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was not valid. Error:\n"
                            f"{exc}\n\nRespond again with ONLY the corrected JSON object, nothing else."
                        ),
                    }
                )
    raise ValueError(f"LLM job '{job}' returned invalid JSON after retry: {last_error}")

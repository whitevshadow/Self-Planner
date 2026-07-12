"""LLM orchestrator — one OpenAI-compatible client, per-job model routing.

Design rule: structured output only. Every job returns JSON that is parsed
and Pydantic-validated by the caller; on failure the call is retried once
with the validation error appended.
"""
import json
import re
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from ..config import settings
from .model_discovery import ensure_env_models_written, list_model_ids, pick_model_for_job

T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


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
        "extract": settings.llm_model_extract,
        "classify": settings.llm_model_classify,
        "plan": settings.llm_model_plan or settings.llm_model_extract,
        "chat": settings.llm_model_chat or settings.llm_model_extract,
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
    return {
        "summary": 700,
        "extract": 1800,
        "classify": 1200,
        "plan": 1200,
        "chat": 1500,
    }.get(job, 1200)


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
    # Only reasoning-capable models (gpt-oss family) take the param; other routes
    # on the gateway stall or 502 when they receive it.
    if settings.llm_reasoning_effort and "gpt-oss" in model:
        extra_body["reasoning_effort"] = settings.llm_reasoning_effort
        # LiteLLM proxies reject non-standard params for some providers unless whitelisted.
        extra_body["allowed_openai_params"] = ["reasoning_effort"]

    last_error: Exception | None = None
    for attempt in range(2):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=_max_tokens_for_job(job),
            extra_body=extra_body,
        )
        raw = resp.choices[0].message.content or ""
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

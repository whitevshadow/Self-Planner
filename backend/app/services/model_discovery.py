from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Iterable

from openai import OpenAI

from ..config import settings

logger = logging.getLogger(__name__)


def _get_client() -> OpenAI:
    if not settings.llm_base_url_resolved or not settings.llm_api_key_resolved:
        raise RuntimeError("LLM not configured: set LLM_BASE_URL/LLM_API_KEY in backend/.env")
    return OpenAI(
        base_url=settings.llm_base_url_resolved,
        api_key=settings.llm_api_key_resolved,
        timeout=settings.llm_timeout_sec,
        max_retries=1,
    )


@lru_cache(maxsize=1)
def list_model_ids() -> list[str]:
    """Return gateway model IDs (OpenAI-compatible). Cached in-process."""
    client = _get_client()
    resp = client.models.list()

    # OpenAI python typically returns objects with `.id`.
    ids: list[str] = []
    for m in getattr(resp, "data", []) or []:
        mid = getattr(m, "id", None)
        if mid:
            ids.append(str(mid))

    # De-dupe while preserving order
    seen = set()
    out: list[str] = []
    for mid in ids:
        if mid not in seen:
            out.append(mid)
            seen.add(mid)

    return out


def pick_model_for_job(job: str, model_ids: Iterable[str]) -> str:
    """Pick a model id for a given job.

    Heuristics:
    - Prefer gpt-oss models (aligns with existing reasoning_effort gating)
    - If multiple exist, choose the first by stable ordering.
    - If none exist, fall back to first available model.

    You can refine these heuristics later (e.g. by context length) once you
    inspect real gateway model naming.
    """
    ids = list(model_ids)
    if not ids:
        raise RuntimeError("Gateway returned no models")

    gpt_oss = [m for m in ids if "gpt-oss" in m.lower()]
    candidates = gpt_oss or ids

    # job-specific tie-breakers could go here.
    # Keep it deterministic: stable ordering from gateway.
    return candidates[0]


def ensure_env_models_written() -> None:
    """Optionally write selected model IDs back into backend/.env.

    This function only writes when it can safely infer values and when
    environment variables are currently empty.

    Note: we do not parse/merge existing comments—this is a best-effort update.
    """
    # Import here to avoid circular import
    import os
    from pathlib import Path

    # If any model is already configured, do not overwrite.
    if settings.llm_model_summary and settings.llm_model_extract and settings.llm_model_classify:
        return

    ids = list_model_ids()
    summary = settings.llm_model_summary or pick_model_for_job("summary", ids)
    extract = settings.llm_model_extract or pick_model_for_job("extract", ids)
    classify = settings.llm_model_classify or pick_model_for_job("classify", ids)

    env_path = Path(__file__).resolve().parents[3] / ".env"  # services -> app -> backend -> repo root
    if not env_path.exists():
        logger.warning("backend/.env not found at %s; skipping env write", env_path)
        return

    # Read & update lines
    raw = env_path.read_text(encoding="utf-8")
    lines = raw.splitlines(True)

    def upsert(key: str, value: str) -> None:
        nonlocal lines
        prefix = f"{key}="
        replaced = False
        for i in range(len(lines)):
            if lines[i].startswith(prefix):
                lines[i] = prefix + value + "\n"
                replaced = True
                break
        if not replaced:
            # append at end
            if lines and not lines[-1].endswith("\n"):
                lines[-1] = lines[-1] + "\n"
            lines.append(prefix + value + "\n")

    upsert("LLM_MODEL_SUMMARY", summary)
    upsert("LLM_MODEL_EXTRACT", extract)
    upsert("LLM_MODEL_CLASSIFY", classify)

    env_path.write_text("".join(lines), encoding="utf-8")

    # Refresh in-process settings is not guaranteed (pydantic-settings already loaded).
    # Caller should rely on returned values rather than settings after write.

    logger.info(
        "Wrote auto-selected LLM model ids to %s: summary=%s extract=%s classify=%s",
        env_path,
        summary,
        extract,
        classify,
    )


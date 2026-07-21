"""Speech-to-text — the only place transcription is touched.

Runs on the OpenAI-compatible gateway's /v1/audio/transcriptions (reuses
LLM_BASE_URL/LLM_API_KEY; model = ASR_MODEL). There is no local ASR backend:
faster-whisper and its CUDA runtime were dropped since every deployment routes
audio through the gateway.

Returns a (segments, duration_sec) contract the pipeline and diarization
consume unchanged.
"""
from typing import TypedDict

from ..config import settings


class SegmentDict(TypedDict):
    idx: int
    start_sec: float
    end_sec: float
    text: str


# Whisper often splits one sentence across several tiny segments; merging them
# back gives readable transcript lines and better diarization/extraction input.
_SENTENCE_END = (".", "?", "!", "…", "।", '"', "'")
_MERGE_MAX_GAP_SEC = 1.0
_MERGE_MAX_CHARS = 250


def _merge_segments(raw: list[tuple[float, float, str]]) -> list[SegmentDict]:
    """Merge (start, end, text) fragments that continue a sentence (small gap,
    previous line has no sentence-final punctuation) into readable segments."""
    out: list[SegmentDict] = []
    for start, end, text in raw:
        text = text.strip()
        if not text:
            continue
        if out:
            prev = out[-1]
            if (
                not prev["text"].endswith(_SENTENCE_END)
                and start - prev["end_sec"] <= _MERGE_MAX_GAP_SEC
                and len(prev["text"]) + len(text) + 1 <= _MERGE_MAX_CHARS
            ):
                prev["text"] += " " + text
                prev["end_sec"] = end
                continue
        out.append({"idx": len(out), "start_sec": start, "end_sec": end, "text": text})
    return out


def transcribe(path: str) -> tuple[list[SegmentDict], float]:
    """Returns (segments, duration_sec) from the gateway's transcription route.

    Note: the gateway is transcribe-only (no /v1/audio/translations), so it
    cannot force non-English speech to English — it returns the transcript in
    the spoken language.
    """
    from openai import OpenAI

    if not settings.llm_base_url_resolved or not settings.llm_api_key_resolved:
        raise RuntimeError(
            "Transcription needs LLM_BASE_URL/LLM_API_KEY in the root .env"
        )
    client = OpenAI(
        base_url=settings.llm_base_url_resolved,
        api_key=settings.llm_api_key_resolved,
        timeout=settings.llm_timeout_sec,
        max_retries=1,
    )
    with open(path, "rb") as fh:
        resp = client.audio.transcriptions.create(
            model=settings.asr_model,
            file=fh,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = getattr(resp, "segments", None) or []
    raw: list[tuple[float, float, str]] = []
    for s in segments:
        start = getattr(s, "start", None)
        end = getattr(s, "end", None)
        text = getattr(s, "text", None)
        if start is None and isinstance(s, dict):  # tolerate dict responses
            start, end, text = s.get("start"), s.get("end"), s.get("text")
        raw.append((float(start or 0.0), float(end or 0.0), text or ""))

    merged = _merge_segments(raw)
    duration = getattr(resp, "duration", None)
    if duration is None:
        duration = merged[-1]["end_sec"] if merged else 0.0
    return merged, float(duration)

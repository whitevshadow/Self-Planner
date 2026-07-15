"""faster-whisper wrapper — the only place Whisper is touched."""
from typing import TypedDict

from ..config import settings


class SegmentDict(TypedDict):
    idx: int
    start_sec: float
    end_sec: float
    text: str


_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute,
        )
    return _model


def preload() -> None:
    _get_model()


# Whisper often splits one sentence across several tiny segments; merging them
# back gives readable transcript lines and better diarization/extraction input.
_SENTENCE_END = (".", "?", "!", "…", "।", '"', "'")
_MERGE_MAX_GAP_SEC = 1.0
_MERGE_MAX_CHARS = 250


def transcribe(path: str) -> tuple[list[SegmentDict], float]:
    """Returns (segments, duration_sec). Consecutive fragments that continue a
    sentence (small gap, previous line has no sentence-final punctuation) are
    merged into one segment."""
    segments, info = _get_model().transcribe(path, task=settings.whisper_task, vad_filter=True)
    out: list[SegmentDict] = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        if out:
            prev = out[-1]
            if (
                not prev["text"].endswith(_SENTENCE_END)
                and s.start - prev["end_sec"] <= _MERGE_MAX_GAP_SEC
                and len(prev["text"]) + len(text) + 1 <= _MERGE_MAX_CHARS
            ):
                prev["text"] += " " + text
                prev["end_sec"] = s.end
                continue
        out.append({"idx": len(out), "start_sec": s.start, "end_sec": s.end, "text": text})
    return out, info.duration

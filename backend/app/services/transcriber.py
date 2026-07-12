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


def transcribe(path: str) -> tuple[list[SegmentDict], float]:
    """Returns (segments, duration_sec)."""
    segments, info = _get_model().transcribe(path, vad_filter=True)
    out: list[SegmentDict] = []
    for i, s in enumerate(segments):
        text = s.text.strip()
        if text:
            out.append({"idx": len(out), "start_sec": s.start, "end_sec": s.end, "text": text})
    return out, info.duration

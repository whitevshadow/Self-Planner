"""pyannote.audio wrapper — speaker turns aligned onto Whisper segments.

Diarization failure must never block the pipeline: any error (missing token,
model download failure, unsupported audio) results in a skip, not a crash.
"""
import logging
import os

from ..config import settings

logger = logging.getLogger(__name__)

_pipeline = None
_load_failed = False


def available() -> bool:
    return bool(settings.hf_token) and not _load_failed


def _get_pipeline():
    global _pipeline, _load_failed
    if _pipeline is None:
        try:
            from pyannote.audio import Pipeline

            _pipeline = Pipeline.from_pretrained(
                settings.diarization_model, token=settings.hf_token
            )
            if _pipeline is None:
                raise RuntimeError(
                    f"Pipeline.from_pretrained returned None — accept the model terms at "
                    f"https://huggingface.co/{settings.diarization_model}"
                )
        except Exception:
            _load_failed = True
            raise
    return _pipeline


def _load_audio(path: str) -> dict:
    """Decode audio to an in-memory waveform via ffmpeg.

    Bypasses pyannote's torchcodec decoding, which needs shared ffmpeg DLLs
    that the static Windows ffmpeg build doesn't provide.
    """
    import glob
    import shutil
    import subprocess
    import tempfile

    import numpy as np
    import torch

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # Fresh winget installs aren't on PATH for already-running shells.
        candidates = glob.glob(
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin\ffmpeg.exe")
        )
        ffmpeg = candidates[0] if candidates else None
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found (required for diarization audio decoding)")

    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
        raw_path = tmp.name
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", path, "-f", "f32le", "-ac", "1", "-ar", "16000", raw_path],
            check=True,
            capture_output=True,
        )
        data = np.fromfile(raw_path, dtype=np.float32)
    finally:
        if os.path.exists(raw_path):
            os.unlink(raw_path)

    waveform = torch.from_numpy(data.copy()).unsqueeze(0)  # (channel, time)
    return {"waveform": waveform, "sample_rate": 16000}


def diarize(path: str) -> list[tuple[float, float, str]]:
    """Audio file → [(start_sec, end_sec, "SPEAKER_00"), ...]."""
    pipeline = _get_pipeline()
    annotation = pipeline(_load_audio(path))
    if not hasattr(annotation, "itertracks"):
        annotation = getattr(annotation, "exclusive_speaker_diarization", None) or getattr(
            annotation, "speaker_diarization", annotation
        )
    return [
        (turn.start, turn.end, label)
        for turn, _, label in annotation.itertracks(yield_label=True)
    ]


def assign_speakers(segments, turns: list[tuple[float, float, str]]) -> None:
    """Set segment.speaker_raw to the speaker with the largest time overlap."""
    for seg in segments:
        best_label, best_overlap = None, 0.0
        for start, end, label in turns:
            overlap = min(seg.end_sec, end) - max(seg.start_sec, start)
            if overlap > best_overlap:
                best_label, best_overlap = label, overlap
        seg.speaker_raw = best_label

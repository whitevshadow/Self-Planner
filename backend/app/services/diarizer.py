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
                    f"https://huggingface.co/{settings.diarization_model} (and its gated "
                    f"dependencies), then confirm HF_TOKEN can read them."
                )
            # pyannote on CPU is slow; move to GPU when one is available.
            try:
                import torch

                if torch.cuda.is_available():
                    _pipeline.to(torch.device("cuda"))
                    logger.info("Diarization pipeline running on CUDA")
            except Exception:
                logger.warning("Could not move diarization pipeline to GPU; using CPU", exc_info=True)
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
    """Label each segment with the best-matching speaker.

    Primary rule: the speaker whose turns overlap the segment the most. When a
    segment falls entirely in a gap between turns (whisper and pyannote don't cut
    audio identically, so this is common), fall back to the nearest turn by time
    so no line is left speaker-less — a blank speaker reads as a diarization bug.
    """
    if not turns:
        return

    for seg in segments:
        seg_mid = (seg.start_sec + seg.end_sec) / 2

        # 1. Sum overlap per speaker (a merged line can span several turns).
        overlap_by_label: dict[str, float] = {}
        for start, end, label in turns:
            overlap = min(seg.end_sec, end) - max(seg.start_sec, start)
            if overlap > 0:
                overlap_by_label[label] = overlap_by_label.get(label, 0.0) + overlap

        if overlap_by_label:
            seg.speaker_raw = max(overlap_by_label, key=overlap_by_label.get)
            continue

        # 2. No overlap — attach to the turn whose span is closest in time.
        def distance(turn: tuple[float, float, str]) -> float:
            start, end, _ = turn
            if seg.end_sec < start:
                return start - seg.end_sec  # segment before the turn
            if seg.start_sec > end:
                return seg.start_sec - end  # segment after the turn
            return abs(((start + end) / 2) - seg_mid)  # nested/adjacent

        seg.speaker_raw = min(turns, key=distance)[2]

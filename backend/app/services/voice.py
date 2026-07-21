"""Voice I/O for the chat assistant — the only place TTS lives, and the
bytes-in speech-to-text used by the live voice loop.

Everything rides the same OpenAI-compatible gateway as the rest of the app
(LLM_BASE_URL/LLM_API_KEY), so no local audio models are required:
- STT  → gateway /v1/audio/transcriptions  (model = ASR_MODEL)
- TTS  → gateway /v1/audio/speech           (model/voice = TTS_* settings)

The chat "brain" is unchanged: routers orchestrate transcribe → chat_agent →
synthesize, so the existing tool-calling agent stays the single source of truth.
"""
from __future__ import annotations

from ..config import settings
from . import orchestrator


class TTSDisabled(RuntimeError):
    """Raised when voice replies are turned off (TTS_PROVIDER=off)."""


def transcribe_bytes(data: bytes, filename: str = "speech.webm") -> str:
    """One utterance of recorded audio → plain transcript text (no timestamps).

    Reuses the gateway ASR route already proven in transcriber.py, but returns
    just the text since the live loop feeds it straight into the chat agent.
    """
    if not data:
        return ""
    client = orchestrator._get_client()
    resp = client.audio.transcriptions.create(
        model=settings.asr_model,
        file=(filename, data),
        response_format="text",
    )
    # response_format="text" yields a plain string; other formats yield an object.
    return (resp if isinstance(resp, str) else getattr(resp, "text", "")).strip()


def synthesize(text: str) -> tuple[bytes, str]:
    """Text → (audio bytes, mime type) using the gateway's /v1/audio/speech.

    Raises TTSDisabled when TTS_PROVIDER=off so the caller can skip audio and
    still return the text reply.
    """
    if settings.tts_provider == "off":
        raise TTSDisabled("voice replies are disabled (set TTS_PROVIDER=gateway to enable)")

    text = (text or "").strip()
    if not text:
        return b"", _mime_for(settings.tts_format)

    client = orchestrator._get_client()
    resp = client.audio.speech.create(
        model=settings.tts_model,
        voice=settings.tts_voice,
        input=text,
        response_format=settings.tts_format,
    )
    # The OpenAI SDK returns a binary response; .read() gives the raw bytes.
    audio = resp.read() if hasattr(resp, "read") else getattr(resp, "content", b"")
    return audio, _mime_for(settings.tts_format)


def _mime_for(fmt: str) -> str:
    return {
        "mp3": "audio/mpeg",
        "opus": "audio/opus",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
    }.get(fmt, "application/octet-stream")

"""Voice endpoints for the live chat loop.

Composable on purpose — the frontend orchestrates transcribe → POST /api/chat
(existing agent) → speak, so the tool-calling agent stays the single brain and
nothing here duplicates chat logic.
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..config import settings
from ..services import voice

router = APIRouter(prefix="/api/voice", tags=["voice"])


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class TranscribeOut(BaseModel):
    text: str


@router.get("/config")
def voice_config():
    """Lets the UI know whether spoken replies are available."""
    return {"tts_enabled": settings.tts_provider != "off"}


@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    if not data:
        raise HTTPException(422, "Empty audio")
    try:
        text = voice.transcribe_bytes(data, audio.filename or "speech.webm")
    except Exception as exc:
        raise HTTPException(500, f"Transcription failed: {exc}")
    return {"text": text}


@router.post("/speak")
def speak(body: SpeakIn):
    try:
        audio, mime = voice.synthesize(body.text)
    except voice.TTSDisabled as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Speech synthesis failed: {exc}")
    if not audio:
        raise HTTPException(500, "Speech synthesis returned no audio")
    return Response(content=audio, media_type=mime)

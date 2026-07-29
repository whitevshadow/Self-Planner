import json
import logging
from datetime import time as dt_time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BusyBlock, ChatMessage
from ..schemas import ChatIn, ChatMessageOut, TimetableEntry
from ..services import chat_agent, timetable
from ..services.timetable import DAY_MAP

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/chat", response_model=list[ChatMessageOut])
def chat_history(limit: int = 50, db: Session = Depends(get_db)):
    msgs = list(db.scalars(select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(limit)))
    return msgs[::-1]


@router.post("/chat", response_model=list[ChatMessageOut])
def chat_message(body: ChatIn, db: Session = Depends(get_db)):
    try:
        return chat_agent.handle_message(db, body.message)
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Chat failed: {exc}")


@router.post("/chat/stream")
def chat_message_stream(body: ChatIn, db: Session = Depends(get_db)):
    """Same turn as POST /chat, streamed as Server-Sent Events.

    The agent spends most of a turn inside its tool loop (query -> add -> replan),
    so the useful thing to stream is STEPS, not tokens: the model emits one JSON
    object per turn, which is not meaningfully parseable until its closing brace.
    """

    def events():
        try:
            for event in chat_agent.stream_message(db, body.message):
                payload = {k: v for k, v in event.items() if k != "_obj"}
                yield f"data: {json.dumps(payload, default=str)}\n\n"
        except Exception as exc:  # never leave the client hanging on a dead stream
            db.rollback()
            logger.exception("chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stop nginx/proxies from buffering the stream
        },
    )


@router.delete("/chat", status_code=204)
def chat_clear(db: Session = Depends(get_db)):
    """Start a new chat: wipe the conversation history."""
    db.query(ChatMessage).delete()
    db.commit()


@router.post("/timetable/parse", response_model=list[TimetableEntry])
def timetable_parse(file: UploadFile = File(...)):
    """Parse a timetable file to a PREVIEW — nothing is saved yet."""
    data = file.file.read()
    if not data:
        raise HTTPException(422, "Empty file")
    try:
        return timetable.parse_upload(file.filename or "upload", data, file.content_type or "")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Timetable parsing failed: {exc}")


@router.post("/timetable/confirm", response_model=dict)
def timetable_confirm(entries: list[TimetableEntry], db: Session = Depends(get_db)):
    """Save confirmed entries as recurring busy blocks."""
    created = 0
    for e in entries:
        h1, m1 = map(int, e.start.split(":"))
        h2, m2 = map(int, e.end.split(":"))
        if (h2, m2) <= (h1, m1):
            continue
        db.add(
            BusyBlock(
                label=e.label,
                weekday=DAY_MAP[e.day],
                start_t=dt_time(h1, m1),
                end_t=dt_time(h2, m2),
                source="timetable",
            )
        )
        created += 1
    db.commit()
    return {"created": created}

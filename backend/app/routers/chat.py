from datetime import time as dt_time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BusyBlock, ChatMessage
from ..schemas import ChatIn, ChatMessageOut, TimetableEntry
from ..services import chat_agent, timetable
from ..services.timetable import DAY_MAP

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

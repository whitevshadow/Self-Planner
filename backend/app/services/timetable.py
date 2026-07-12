"""Timetable ingestion: image / PDF / CSV-Excel / plain text → busy-block entries.

Parsed entries are returned as a PREVIEW — nothing is written until the user
confirms (LLM parsing of documents is fallible by design assumption).
"""
import base64
import io
import json
import logging

from ..config import settings
from ..schemas import TimetableEntry, TimetableParseResult
from . import orchestrator

logger = logging.getLogger(__name__)

DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

PARSE_SYSTEM = """You convert timetables/schedules into structured busy blocks.
Respond with ONLY a JSON object, no prose, matching exactly:
{"entries": [{"day": "mon"|"tue"|"wed"|"thu"|"fri"|"sat"|"sun", "start": "HH:MM", "end": "HH:MM", "label": str}]}

Rules:
- One entry per (day, time-range, activity). A class on Mon and Wed = two entries.
- 24-hour times. If the source uses AM/PM, convert.
- label: short activity name ("Gym", "Math lecture").
- Skip free periods, lunch gaps marked as free, and empty cells.
- If the input is not a timetable at all, return {"entries": []}.
"""


def parse_text(text: str) -> list[TimetableEntry]:
    result = orchestrator.run_json_job(
        "chat", PARSE_SYSTEM, f"Timetable input:\n\n{text}", TimetableParseResult
    )
    return result.entries


def parse_pdf(data: bytes) -> list[TimetableEntry]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(text.strip()) < 20:
        raise ValueError("PDF has no extractable text (scanned PDF?) — try a screenshot upload instead")
    return parse_text(text)


def parse_tabular(data: bytes, filename: str) -> list[TimetableEntry]:
    import pandas as pd

    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(data))
    else:
        df = pd.read_csv(io.BytesIO(data))
    # Hand the table to the LLM as CSV text — it maps unfamiliar headers.
    return parse_text(df.to_csv(index=False))


def parse_image(data: bytes, content_type: str) -> list[TimetableEntry]:
    """Vision model call via the same OpenAI-compatible gateway."""
    client = orchestrator._get_client()
    b64 = base64.b64encode(data).decode()
    resp = client.chat.completions.create(
        model=settings.llm_model_vision,
        messages=[
            {"role": "system", "content": PARSE_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract the timetable from this image."},
                    {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
                ],
            },
        ],
        temperature=0.2,
        max_tokens=1500,
    )
    raw = resp.choices[0].message.content or ""
    return TimetableParseResult.model_validate(orchestrator._extract_json(raw)).entries


def parse_upload(filename: str, data: bytes, content_type: str) -> list[TimetableEntry]:
    name = filename.lower()
    if name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return parse_image(data, content_type or "image/png")
    if name.endswith(".pdf"):
        return parse_pdf(data)
    if name.endswith((".csv", ".xlsx", ".xls")):
        return parse_tabular(data, name)
    if name.endswith(".txt"):
        return parse_text(data.decode("utf-8", errors="replace"))
    raise ValueError(f"Unsupported timetable format: {filename}")

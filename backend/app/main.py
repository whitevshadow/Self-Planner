from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select

from datetime import time

from .db import Base, SessionLocal, engine
from .migrations import run_migrations
from .models import AvailabilityRule, Person
from .routers import chat, export, meetings, people, planner, tasks, voice
from .services import pipeline, scheduler_jobs, storage


def _seed_me() -> None:
    with SessionLocal() as db:
        if not db.scalar(select(Person).where(Person.is_me)):
            db.add(Person(name="Anish", aliases=["anish", "AB"], is_me=True))
            db.commit()


def _seed_availability() -> None:
    """Defaults per phase4.md: work Mon–Fri 10:00–19:00, personal Sat–Sun 12:00–18:00.
    Weekday evenings deliberately have no availability at all."""
    with SessionLocal() as db:
        if db.scalar(select(AvailabilityRule).limit(1)):
            return
        for wd in range(5):
            db.add(AvailabilityRule(category="work", weekday=wd, start_t=time(10, 0), end_t=time(19, 0)))
        for wd in (5, 6):
            db.add(AvailabilityRule(category="personal", weekday=wd, start_t=time(12, 0), end_t=time(18, 0)))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_migrations()
    _seed_me()
    _seed_availability()
    storage.ensure_bucket()
    # A restart kills in-process background stages; release rows they left behind.
    pipeline.reclaim_orphans()
    scheduler_jobs.start()
    yield
    scheduler_jobs.shutdown()


app = FastAPI(title="Self Planner", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    # So the browser can read the export's download filename cross-origin.
    expose_headers=["Content-Disposition"],
)

app.include_router(meetings.router)
app.include_router(tasks.router)
app.include_router(people.router)
app.include_router(planner.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(export.router)


@app.get("/api/health")
def health():
    return {"ok": True}

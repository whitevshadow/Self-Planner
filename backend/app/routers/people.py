import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Person
from ..schemas import PersonIn, PersonOut

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("", response_model=list[PersonOut])
def list_people(db: Session = Depends(get_db)):
    return db.scalars(select(Person).order_by(Person.name)).all()


@router.post("", response_model=PersonOut, status_code=201)
def create_person(body: PersonIn, db: Session = Depends(get_db)):
    if db.scalar(select(Person).where(Person.name.ilike(body.name.strip()))):
        raise HTTPException(409, f"'{body.name}' already exists")
    person = Person(name=body.name.strip(), aliases=body.aliases, is_me=body.is_me)
    if body.is_me:
        _clear_other_is_me(db)
    db.add(person)
    db.commit()
    return person


@router.patch("/{person_id}", response_model=PersonOut)
def update_person(person_id: uuid.UUID, body: PersonIn, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    if body.is_me and not person.is_me:
        _clear_other_is_me(db)
    person.name = body.name.strip()
    person.aliases = body.aliases
    person.is_me = body.is_me
    db.commit()
    return person


@router.delete("/{person_id}", status_code=204)
def delete_person(person_id: uuid.UUID, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    if person.is_me:
        raise HTTPException(422, "Cannot delete the 'me' person")
    db.delete(person)
    db.commit()


def _clear_other_is_me(db: Session) -> None:
    # App-enforced invariant: exactly one person has is_me=true.
    for p in db.scalars(select(Person).where(Person.is_me)).all():
        p.is_me = False

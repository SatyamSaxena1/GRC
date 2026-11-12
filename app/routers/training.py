"""Training (ADR-063): something every member reads and says they understood, repeated on a cycle.

What is kept, and nothing inferred: the text of each course version, and who said they read and understood which
version on which day. A person is DONE while that statement is newer than the course's cycle (a year by default) and is
for the current version; editing the text makes a new version that everyone does again. An organisation admin writes
courses; every member completes them for themselves. It is a statement, not a test: it shows a person was given the
material and said so, which is what an auditor asks to see for staff awareness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import TrainingCompletion, TrainingCourse, User

router = APIRouter(prefix="/training", tags=["training"])

DUE_SOON_DAYS = 30

# Starting points, in our own words. An admin edits them before relying on them.
TEMPLATES: dict[str, tuple[str, str]] = {
    "security-awareness": ("Security awareness", """Why this matters
Most security incidents start with an ordinary person making an ordinary mistake. This takes ten minutes to read.

1. Passwords and sign-in
Use a password manager. Never reuse a work password. Turn on multi-factor authentication wherever it is offered, and never read a one-time code out to anyone.

2. Phishing
Be suspicious of any message that rushes you, asks for money or a password, or comes from an address you do not know. If in doubt, do not click: report it to the security contact.

3. Your devices
Lock your screen when you step away. Keep your laptop and phone updated and encrypted. Report a lost or stolen device straight away, even if you think it was empty.

4. Handling data
Keep customer data in the approved systems. Do not email it to a personal address, copy it to a USB stick or paste it into an AI tool the company has not approved.

5. Reporting
If you see something odd, report it. Nobody is blamed for reporting in good faith, and early reports are what stop small problems becoming incidents."""),
    "data-protection-basics": ("Data protection basics", """Why this matters
We hold personal data about our customers and our own people. The law, and our customers, expect us to look after it.

1. What counts as personal data
Anything that identifies a person: a name, email, phone number, account number, device identifier or a photo.

2. Use it only for what it was collected for
Collect only what you need, use it only for the stated purpose, and do not keep it longer than the retention policy says.

3. Share carefully
Share personal data only with people who need it and with suppliers that have been approved. Never send it through personal accounts.

4. People's rights
A person can ask to see, correct or delete their data. If someone asks, pass it to the privacy contact the same day: the clock starts when they ask, not when we notice.

5. If something goes wrong
A lost file, a wrong recipient or a suspected breach must be reported to the privacy contact immediately. The law gives us a short time to notify, and we need every hour of it."""),
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _member(actor: Actor) -> Actor:
    """Anyone on the organisation's own side. An auditor reads evidence, not the internal training."""
    if actor.engagement_id or not actor.org_id:
        raise HTTPException(403, "training is for members of the organisation")
    return actor


def _admin(actor: Actor) -> Actor:
    if _member(actor).role != "ORG_ADMIN":
        raise HTTPException(403, "only an organisation admin may write a course")
    return actor


def _people(db: Session, org_id: str) -> dict[str, str]:
    """The active members expected to complete: id -> email."""
    return {u.id: u.email for u in db.query(User).filter(User.org_id == org_id, User.active.is_(True))}


def state(completed_at: datetime | None, cycle_days: int, now: datetime | None = None) -> tuple[str, str | None]:
    """(NOT_DONE | DONE | DUE_SOON | OVERDUE, the date it is next due). From the latest completion of the current
    version alone."""
    if completed_at is None:
        return "NOT_DONE", None
    now = now or _now()
    due = completed_at + timedelta(days=cycle_days)
    left = (due - now).days
    return ("OVERDUE" if due <= now else "DUE_SOON" if left <= DUE_SOON_DAYS else "DONE"), due.date().isoformat()


def _latest(db: Session, c: TrainingCourse) -> dict[str, datetime]:
    """user id -> their latest completion of the CURRENT version."""
    latest: dict[str, datetime] = {}
    for r in db.query(TrainingCompletion).filter_by(org_id=c.org_id, course_id=c.id, version=c.version):
        if r.user_id not in latest or r.completed_at > latest[r.user_id]:
            latest[r.user_id] = r.completed_at
    return latest


def _out(c: TrainingCourse, people: dict[str, str], latest: dict[str, datetime], actor: Actor, body: bool = False) -> dict:
    mine, mine_due = state(latest.get(actor.user_id) if actor.user_id else None, c.cycle_days)
    states = {uid: state(latest.get(uid), c.cycle_days)[0] for uid in people}
    out = {"id": c.id, "title": c.title, "version": c.version, "cycle_days": c.cycle_days,
           "people": len(people), "up_to_date": sum(1 for s in states.values() if s in ("DONE", "DUE_SOON")),
           "my_state": mine, "my_due": mine_due}
    if actor.role == "ORG_ADMIN":
        out["waiting_on"] = sorted(people[uid] for uid, s in states.items() if s in ("NOT_DONE", "OVERDUE"))
    if body:
        out["body"] = c.body
    return out


def _load(db: Session, actor: Actor, course_id: str) -> TrainingCourse:
    c = db.get(TrainingCourse, course_id)
    if c is None or c.org_id != actor.org_id:
        raise HTTPException(404)
    return c


@router.get("/templates")
def list_templates(actor: Actor = Depends(current_actor)):
    _admin(actor)
    return [{"id": tid, "title": title} for tid, (title, _) in TEMPLATES.items()]


@router.get("")
def list_courses(actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _member(actor)
    people = _people(db, actor.org_id)
    rows = db.query(TrainingCourse).filter_by(org_id=actor.org_id).order_by(TrainingCourse.title).all()
    return {"can_manage": actor.role == "ORG_ADMIN", "courses": [_out(c, people, _latest(db, c), actor) for c in rows]}


@router.get("/{course_id}")
def get_course(course_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    c = _load(db, _member(actor), course_id)
    return _out(c, _people(db, actor.org_id), _latest(db, c), actor, body=True)


class CourseIn(BaseModel):
    """Either a template to start from, or a title and text of your own."""
    template_id: str | None = None
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=20, max_length=100_000)
    cycle_days: int = Field(default=365, ge=30, le=730)


@router.post("", status_code=201)
def add_course(body: CourseIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    if body.template_id:
        if body.template_id not in TEMPLATES:
            raise HTTPException(422, "unknown template")
        title, text = TEMPLATES[body.template_id]
        title = body.title or title
    elif body.title and body.body:
        title, text = body.title, body.body
    else:
        raise HTTPException(422, "give a template, or a title and the text")
    c = TrainingCourse(org_id=actor.org_id, title=title.strip(), body=text, cycle_days=body.cycle_days,
                       created_by=actor.label(), created_at=_now())
    db.add(c)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TRAINING_ADDED",
                     entity_type="training_course", entity=c.id, org_id=actor.org_id,
                     after={"title": c.title, "version": 1, "cycle_days": c.cycle_days, "template": body.template_id})
    db.commit()
    return _out(c, _people(db, actor.org_id), {}, actor, body=True)


class CourseEdit(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=20, max_length=100_000)
    cycle_days: int | None = Field(default=None, ge=30, le=730)


@router.put("/{course_id}")
def edit_course(course_id: str, body: CourseEdit, actor: Actor = Depends(current_actor),
                db: Session = Depends(get_session)):
    """A change to the text is a new version that everyone completes again. A change to the title or cycle alone is not."""
    c = _load(db, _admin(actor), course_id)
    title, text = (body.title or c.title).strip(), body.body if body.body is not None else c.body
    cycle = body.cycle_days or c.cycle_days
    if (title, text, cycle) != (c.title, c.body, c.cycle_days):
        before = {"title": c.title, "version": c.version, "cycle_days": c.cycle_days}
        new_text = text != c.body
        c.title, c.body, c.cycle_days = title, text, cycle
        if new_text:
            c.version += 1
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TRAINING_EDITED",
                         entity_type="training_course", entity=c.id, org_id=actor.org_id, before=before,
                         after={"title": c.title, "version": c.version, "cycle_days": c.cycle_days})
        db.commit()
    return _out(c, _people(db, actor.org_id), _latest(db, c), actor, body=True)


class Seen(BaseModel):
    """The version on the caller's screen: completing anything else is refused, so nobody confirms text that changed
    after they read it."""
    version: int


@router.post("/{course_id}/complete")
def complete(course_id: str, seen: Seen, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    """A person says they read and understood the version on their screen, for themselves. Asking again while still
    up to date changes nothing."""
    c = _load(db, _member(actor), course_id)
    if not actor.user_id:
        raise HTTPException(422, "sign in as a named person to complete training")
    if seen.version != c.version:
        raise HTTPException(409, f"this course is now at version {c.version}; open it again and read the new text")
    latest = _latest(db, c)
    if state(latest.get(actor.user_id), c.cycle_days)[0] not in ("DONE",):
        now = _now()
        db.add(TrainingCompletion(org_id=c.org_id, course_id=c.id, version=c.version, user_id=actor.user_id,
                                  completed_at=now))
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TRAINING_COMPLETED",
                         entity_type="training_course", entity=c.id, org_id=actor.org_id,
                         after={"version": c.version, "title": c.title})
        db.commit()
        latest[actor.user_id] = now
    return _out(c, _people(db, actor.org_id), latest, actor)

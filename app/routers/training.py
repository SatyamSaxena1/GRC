"""Training (ADR-063): something every member reads and says they understood, repeated on a cycle.

What is kept, and nothing inferred: the text of each course version, and who said they read and understood which
version on which day. A person is DONE while that statement is newer than the course's cycle (a year by default) and is
for the current version; editing the text makes a new version that everyone does again. An organisation admin writes
courses; every member completes them for themselves. It is a statement, not a test: it shows a person was given the
material and said so, which is what an auditor asks to see for staff awareness.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app import audit_log
from app.auth import Actor, current_actor
from app.db import get_session
from app.models import TrainingAttempt, TrainingCompletion, TrainingCourse, User

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
    "using-grc": ("Using GRC: the basics", """Three short lessons on how this platform works, each ending with a few situations to answer. Try as often as you like: your best try at each lesson counts. 80% right is a pass, 50% is a partial.

Drafted with AI help: an admin should read and adjust it before relying on it."""),
}


def _q(scenario: str, choices: list[str], answer: int, why: str) -> dict:
    return {"scenario": scenario, "choices": choices, "answer": answer, "why": why}


# Lessons for the templates that have them (ADR-064). In our own words; drafted with AI help, to be reviewed.
TEMPLATE_LESSONS: dict[str, list[dict]] = {
    "using-grc": [
        {"title": "Evidence and verdicts", "body": """Evidence is a fact the platform read, or a file someone added: a cloud setting, a report, an export.

Each control has rules. A rule reads the evidence and gives a verdict: PASS, FAIL, PARTIAL, or NO_EVIDENCE when there is nothing to read yet. When evidence has expired, a gap marked STALE appears.

Rules decide verdicts. An AI model may draft text, such as a summary or a policy, but it never decides whether a control passes.""",
         "questions": [
             _q("A control shows NO_EVIDENCE. Your manager asks whether that means the company failed it.",
                ["Yes, NO_EVIDENCE is the same as FAIL",
                 "No: the rule has nothing to read yet, so add or connect the evidence",
                 "It means an AI looked and was not sure"], 1,
                "NO_EVIDENCE says the rule had nothing to read. It is not a failure, and it is not a pass either."),
             _q("An AI-drafted summary says a control 'looks fine', but the rule says FAIL. What does the platform show?",
                ["PASS, because the summary is newer", "FAIL, because the rule decides the verdict",
                 "Both, and you pick one"], 1,
                "A model only drafts. The verdict always comes from the rule reading the evidence."),
             _q("Last year's access review is the only evidence for a yearly control, and a STALE gap appears.",
                ["Nothing to do: it passed last year", "Do this year's review and add it as new evidence",
                 "Delete the old evidence so the warning goes away"], 1,
                "STALE means the evidence has expired. New evidence closes the gap; deleting history never does."),
         ]},
        {"title": "Statements and policies", "body": """Some controls have no rule yet. For those, a named person makes a dated statement that the control is in place. It shows as ATTESTED, never as PASS, so an auditor can tell a person's word from a rule's verdict.

Policies are your own documents. A new or changed policy is a draft until an admin approves it, and then each person accepts the approved version. Changing the words makes a new version that people accept again.""",
         "questions": [
             _q("You change one sentence in the approved access control policy. What happens?",
                ["Nothing: small edits keep the approval",
                 "It becomes a new draft version that an admin approves and people accept again",
                 "The policy is deleted and made again"], 1,
                "Any change to the words is a new version. People accepted the old words, so they accept the new ones."),
             _q("A control has no rule. Your CTO says 'just mark it passed'.",
                ["Make a dated statement as the person responsible; it shows as ATTESTED",
                 "Ask support to set it to PASS", "Upload any file so it turns green"], 0,
                "Only a rule can give PASS. A named person's dated statement is the honest way, and it reads ATTESTED."),
         ]},
        {"title": "Auditors and the record", "body": """An auditor gets their own access to one engagement. They read the evidence and verdicts for it; they cannot change your data, and they do not see internal pages such as training.

Every change anyone makes is written to the activity log: who, what and when. Policies are archived, not deleted.""",
         "questions": [
             _q("An auditor asks you to email them a spreadsheet of every control.",
                ["Email it from your laptop",
                 "Point them to their engagement in GRC, where they can read the evidence and verdicts",
                 "Share your own login with them"], 1,
                "The engagement gives the auditor read access to what they need. Never share a login."),
             _q("A colleague wants to know who changed a risk's owner last week.",
                ["Ask around the team", "Look it up in the activity log", "It cannot be known"], 1,
                "Every change is recorded with who, what and when."),
         ]},
    ],
}

PASS_PCT, PARTIAL_PCT = 80, 50


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


def result(best: dict[int, tuple[int, int]], lessons: int) -> tuple[str, int | None]:
    """(NOT_STARTED | IN_PROGRESS | PASS | PARTIAL | FAIL, percent right). From each lesson's best try alone (ADR-064)."""
    if not best:
        return "NOT_STARTED", None
    if len(best) < lessons:
        return "IN_PROGRESS", None
    right, asked = sum(r for r, _ in best.values()), sum(t for _, t in best.values())
    pct = 100 if asked == 0 else 100 * right // asked
    return ("PASS" if pct >= PASS_PCT else "PARTIAL" if pct >= PARTIAL_PCT else "FAIL"), pct


def _best(db: Session, c: TrainingCourse) -> dict[str, dict[int, tuple[int, int]]]:
    """user id -> lesson -> (right, asked) of their best try at the CURRENT version."""
    best: dict[str, dict[int, tuple[int, int]]] = {}
    for a in db.query(TrainingAttempt).filter_by(org_id=c.org_id, course_id=c.id, version=c.version):
        mine = best.setdefault(a.user_id, {})
        if a.lesson not in mine or a.correct > mine[a.lesson][0]:
            mine[a.lesson] = (a.correct, a.total)
    return best


def _progress(best: dict[int, tuple[int, int]], lessons: int) -> dict:
    res, pct = result(best, lessons)
    return {"done": len(best), "lessons": lessons, "result": res, "score": pct,
            "by_lesson": [list(best[i]) if i in best else None for i in range(lessons)]}


def _public(lessons: list[dict]) -> list[dict]:
    """The lessons without the answers, which a person sees only after they answer."""
    return [{"title": l["title"], "body": l["body"],
             "questions": [{"scenario": q["scenario"], "choices": q["choices"]} for q in l["questions"]]}
            for l in lessons]


def _out(db: Session, c: TrainingCourse, people: dict[str, str], latest: dict[str, datetime], actor: Actor,
         body: bool = False) -> dict:
    mine, mine_due = state(latest.get(actor.user_id) if actor.user_id else None, c.cycle_days)
    states = {uid: state(latest.get(uid), c.cycle_days)[0] for uid in people}
    n = len(c.lessons or [])
    out = {"id": c.id, "title": c.title, "version": c.version, "cycle_days": c.cycle_days,
           "people": len(people), "up_to_date": sum(1 for s in states.values() if s in ("DONE", "DUE_SOON")),
           "my_state": mine, "my_due": mine_due, "lesson_count": n}
    if n:
        best = _best(db, c)
        out["my_progress"] = _progress(best.get(actor.user_id, {}), n)
    if actor.role == "ORG_ADMIN":
        out["waiting_on"] = sorted(people[uid] for uid, s in states.items() if s in ("NOT_DONE", "OVERDUE"))
        if n:
            out["results"] = sorted(({"email": email, **_progress(best.get(uid, {}), n)} for uid, email in people.items()),
                                    key=lambda r: r["email"])
    if body:
        out["body"] = c.body
        out["lessons"] = _public(c.lessons or [])
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
    return {"can_manage": actor.role == "ORG_ADMIN", "courses": [_out(db, c, people, _latest(db, c), actor) for c in rows]}


@router.get("/{course_id}")
def get_course(course_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    c = _load(db, _member(actor), course_id)
    return _out(db, c, _people(db, actor.org_id), _latest(db, c), actor, body=True)


class QuestionIn(BaseModel):
    scenario: str = Field(min_length=5, max_length=2000)
    choices: list[str] = Field(min_length=2, max_length=6)
    answer: int = Field(ge=0)
    why: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _answer_is_a_choice(self):
        if self.answer >= len(self.choices) or any(not c.strip() for c in self.choices):
            raise ValueError("the answer must be one of the choices, and no choice may be empty")
        return self


class LessonIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=1, max_length=50_000)
    questions: list[QuestionIn] = Field(default_factory=list, max_length=20)


Lessons = list[LessonIn] | None


class CourseIn(BaseModel):
    """Either a template to start from, or a title and text of your own (and, if you like, lessons)."""
    template_id: str | None = None
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=20, max_length=100_000)
    lessons: Lessons = Field(default=None, max_length=30)
    cycle_days: int = Field(default=365, ge=30, le=730)


@router.post("", status_code=201)
def add_course(body: CourseIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_session)):
    _admin(actor)
    if body.template_id:
        if body.template_id not in TEMPLATES:
            raise HTTPException(422, "unknown template")
        title, text = TEMPLATES[body.template_id]
        title = body.title or title
        lessons = copy.deepcopy(TEMPLATE_LESSONS.get(body.template_id, []))
    elif body.title and body.body:
        title, text = body.title, body.body
        lessons = [l.model_dump() for l in body.lessons or []]
    else:
        raise HTTPException(422, "give a template, or a title and the text")
    c = TrainingCourse(org_id=actor.org_id, title=title.strip(), body=text, cycle_days=body.cycle_days,
                       lessons=lessons, created_by=actor.label(), created_at=_now())
    db.add(c)
    db.flush()
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TRAINING_ADDED",
                     entity_type="training_course", entity=c.id, org_id=actor.org_id,
                     after={"title": c.title, "version": 1, "cycle_days": c.cycle_days, "template": body.template_id,
                            "lessons": len(lessons)})
    db.commit()
    return _out(db, c, _people(db, actor.org_id), {}, actor, body=True)


class CourseEdit(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=20, max_length=100_000)
    cycle_days: int | None = Field(default=None, ge=30, le=730)
    lessons: Lessons = Field(default=None, max_length=30)


@router.put("/{course_id}")
def edit_course(course_id: str, body: CourseEdit, actor: Actor = Depends(current_actor),
                db: Session = Depends(get_session)):
    """A change to the text or lessons is a new version that everyone completes again. A change to the title or cycle
    alone is not."""
    c = _load(db, _admin(actor), course_id)
    title, text = (body.title or c.title).strip(), body.body if body.body is not None else c.body
    cycle = body.cycle_days or c.cycle_days
    lessons = [l.model_dump() for l in body.lessons] if body.lessons is not None else (c.lessons or [])
    if (title, text, cycle, lessons) != (c.title, c.body, c.cycle_days, c.lessons or []):
        before = {"title": c.title, "version": c.version, "cycle_days": c.cycle_days, "lessons": len(c.lessons or [])}
        new_text = text != c.body or lessons != (c.lessons or [])
        c.title, c.body, c.cycle_days, c.lessons = title, text, cycle, lessons
        if new_text:
            c.version += 1
        audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TRAINING_EDITED",
                         entity_type="training_course", entity=c.id, org_id=actor.org_id, before=before,
                         after={"title": c.title, "version": c.version, "cycle_days": c.cycle_days,
                                "lessons": len(lessons)})
        db.commit()
    return _out(db, c, _people(db, actor.org_id), _latest(db, c), actor, body=True)


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
    return _out(db, c, _people(db, actor.org_id), latest, actor)


class Answers(BaseModel):
    """The version on the caller's screen, and the index of the choice picked for each question, in order."""
    version: int
    answers: list[int] = Field(max_length=20)


@router.post("/{course_id}/lessons/{lesson}/answer")
def answer(course_id: str, lesson: int, body: Answers, actor: Actor = Depends(current_actor),
           db: Session = Depends(get_session)):
    """Grade one try at one lesson against the stored answers (a fixed rule, never a model), keep it, and only now
    show the right answer and why. Every try is kept; the best one counts (ADR-064)."""
    c = _load(db, _member(actor), course_id)
    if not actor.user_id:
        raise HTTPException(422, "sign in as a named person to answer")
    if body.version != c.version:
        raise HTTPException(409, f"this course is now at version {c.version}; open it again and read the new text")
    lessons = c.lessons or []
    if not 0 <= lesson < len(lessons):
        raise HTTPException(404, "no such lesson")
    questions = lessons[lesson]["questions"]
    if len(body.answers) != len(questions):
        raise HTTPException(422, f"answer all {len(questions)} questions")
    marked = [{"picked": a, "answer": q["answer"], "right": a == q["answer"], "why": q["why"]}
              for a, q in zip(body.answers, questions)]
    right = sum(m["right"] for m in marked)
    db.add(TrainingAttempt(org_id=c.org_id, course_id=c.id, version=c.version, lesson=lesson, user_id=actor.user_id,
                           answers=body.answers, correct=right, total=len(questions), created_at=_now()))
    audit_log.record(db, actor=actor.label(), request_id=actor.request_id, action="TRAINING_ANSWERED",
                     entity_type="training_course", entity=c.id, org_id=actor.org_id,
                     after={"version": c.version, "lesson": lesson, "right": right, "of": len(questions)})
    db.commit()
    out = _out(db, c, _people(db, actor.org_id), _latest(db, c), actor)
    return {"right": right, "of": len(questions), "marked": marked, "course": out}

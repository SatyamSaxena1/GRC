"""All tables. One file — the slice's entity count doesn't earn a package.

Tenant-owned rows all carry org_id; see app/authorization.py for the access
rules and alembic/versions/*_rls.py for the Postgres row-level enforcement.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- tenancy


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str]
    frameworks: Mapped[list[str]] = mapped_column(JSON, default=list)  # subscribed framework codes


class AuditFirm(Base):
    __tablename__ = "audit_firms"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str]


class User(Base):
    """Belongs to exactly one org OR one audit firm, never both."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str]
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), default=None)
    audit_firm_id: Mapped[str | None] = mapped_column(ForeignKey("audit_firms.id"), default=None)
    role: Mapped[str] = mapped_column(String, default="CONTROL_OWNER")  # ORG_ADMIN|CONTROL_OWNER|AUDITOR


class Engagement(Base):
    """The only thing that lets an auditor see an auditee's rows."""
    __tablename__ = "engagements"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    audit_firm_id: Mapped[str] = mapped_column(ForeignKey("audit_firms.id"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    status: Mapped[str] = mapped_column(String, default="ACTIVE")  # ACTIVE | CLOSED
    period_start: Mapped[datetime | None] = mapped_column(default=None)
    period_end: Mapped[datetime | None] = mapped_column(default=None)
    closed_at: Mapped[datetime | None] = mapped_column(default=None)

    allocations: Mapped[list["EngagementAllocation"]] = relationship(back_populates="engagement")

    @property
    def active(self) -> bool:
        return self.status == "ACTIVE"


class EngagementAllocation(Base):
    """Scope of an engagement. An auditor sees only allocated frameworks — an
    active engagement alone is not enough."""
    __tablename__ = "engagement_allocations"
    __table_args__ = (UniqueConstraint("engagement_id", "framework"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"))
    framework: Mapped[str]

    engagement: Mapped[Engagement] = relationship(back_populates="allocations")


# --------------------------------------------------------------------------- controls


class OrgControl(Base):
    """An organization's instance of one framework requirement."""
    __tablename__ = "org_controls"
    __table_args__ = (UniqueConstraint("org_id", "framework", "clause"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    framework: Mapped[str]
    clause: Mapped[str]

    assignments: Mapped[list["ControlAssignment"]] = relationship(back_populates="org_control")


class ControlAssignment(Base):
    """A control owner's access grant. Not a label — the authorization check."""
    __tablename__ = "control_assignments"
    __table_args__ = (UniqueConstraint("org_control_id", "user_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_control_id: Mapped[str] = mapped_column(ForeignKey("org_controls.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(default=_now)

    org_control: Mapped[OrgControl] = relationship(back_populates="assignments")


# --------------------------------------------------------------------------- evidence

# Worker lifecycle. READY and the two terminal problem states end processing.
EVIDENCE_STATUSES = (
    "UPLOADED", "SCANNING", "STORED", "EXTRACTING", "ANALYZING",
    "EVALUATING", "READY", "FAILED", "NEEDS_REVIEW",
)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    artefact_type: Mapped[str] = mapped_column(String, default="POLICY")

    original_filename: Mapped[str] = mapped_column(default="")
    filename: Mapped[str] = mapped_column(default="")  # sanitized
    mime_type: Mapped[str] = mapped_column(default="")
    size_bytes: Mapped[int] = mapped_column(default=0)
    sha256: Mapped[str] = mapped_column(String, default="")
    storage_key: Mapped[str] = mapped_column(default="")
    uploaded_by: Mapped[str] = mapped_column(default="")

    version: Mapped[int] = mapped_column(default=1)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"), default=None)
    extracted_attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="UPLOADED")
    status_detail: Mapped[str] = mapped_column(Text, default="")
    quality_score: Mapped[float | None] = mapped_column(default=None)      # 0-5
    quality_detail: Mapped[dict] = mapped_column(JSON, default=dict)       # per-dimension reasons
    lifecycle_status: Mapped[str] = mapped_column(String, default="CURRENT")  # CURRENT|SUPERSEDED
    created_at: Mapped[datetime] = mapped_column(default=_now)

    links: Mapped[list["EvidenceControlLink"]] = relationship(back_populates="evidence")
    attributes: Mapped[list["EvidenceAttribute"]] = relationship(back_populates="evidence")


class EvidenceAttribute(Base):
    """One extracted fact with its provenance. Normalized rather than buried in
    a JSON blob so provenance is queryable (which page supports which verdict)."""
    __tablename__ = "evidence_attributes"
    __table_args__ = (UniqueConstraint("evidence_id", "name"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    name: Mapped[str]
    value_json: Mapped[dict] = mapped_column(JSON, default=dict)  # {"v": <any>} — wrapped so null is storable
    confidence: Mapped[float | None] = mapped_column(default=None)
    extraction_method: Mapped[str] = mapped_column(String, default="")  # native_text|vlm|none
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{"page":n,"quote":"..."}]

    evidence: Mapped[Evidence] = relationship(back_populates="attributes")

    @property
    def value(self):
        return self.value_json.get("v")


class EvidenceControlLink(Base):
    """One row per evidence x requirement. AI provenance lives here."""
    __tablename__ = "evidence_control_links"
    __table_args__ = (UniqueConstraint("evidence_id", "framework", "clause"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    framework: Mapped[str]
    clause: Mapped[str]
    ucos: Mapped[list[str]] = mapped_column(JSON, default=list)
    verdict: Mapped[str] = mapped_column(String)  # PASS|PARTIAL|FAIL
    rationale: Mapped[str] = mapped_column(Text, default="")
    ai_model: Mapped[str] = mapped_column(String, default="")
    ai_prompt_version: Mapped[str] = mapped_column(String, default="")
    ai_confidence: Mapped[float | None] = mapped_column(default=None)  # null until a real confidence exists

    auditor_verdict: Mapped[str | None] = mapped_column(default=None)
    locked_by_engagement_id: Mapped[str | None] = mapped_column(
        ForeignKey("engagements.id"), default=None
    )
    locked_at: Mapped[datetime | None] = mapped_column(default=None)
    unlocked_at: Mapped[datetime | None] = mapped_column(default=None)
    unlock_reason: Mapped[str | None] = mapped_column(Text, default=None)

    evidence: Mapped[Evidence] = relationship(back_populates="links")
    gaps: Mapped[list["GapRow"]] = relationship(back_populates="link")

    @property
    def locked(self) -> bool:
        return self.locked_by_engagement_id is not None


class GapRow(Base):
    __tablename__ = "gaps"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    link_id: Mapped[str] = mapped_column(ForeignKey("evidence_control_links.id"))
    kind: Mapped[str]
    attribute: Mapped[str]
    detail: Mapped[str] = mapped_column(Text)
    required_action: Mapped[str] = mapped_column(Text, default="")
    actual_value: Mapped[str | None] = mapped_column(default=None)
    required_value: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN|RESOLVED_BY_EVIDENCE
    created_at: Mapped[datetime] = mapped_column(default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)
    resolved_by_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"), default=None)
    resolution_reason: Mapped[str | None] = mapped_column(default=None)

    link: Mapped[EvidenceControlLink] = relationship(back_populates="gaps")
    tasks: Mapped[list["TaskRow"]] = relationship(back_populates="gap")

    @property
    def open(self) -> bool:
        return self.status == "OPEN"


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    gap_id: Mapped[str] = mapped_column(ForeignKey("gaps.id"))
    title: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    due_at: Mapped[datetime | None] = mapped_column(default=None)
    priority: Mapped[str] = mapped_column(String, default="MEDIUM")  # LOW|MEDIUM|HIGH|CRITICAL
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN|DONE
    created_at: Mapped[datetime] = mapped_column(default=_now)

    gap: Mapped[GapRow] = relationship(back_populates="tasks")


# --------------------------------------------------------------------------- audit / AI


class AiRun(Base):
    """Every model call, kept so an AI-assisted decision can be explained later.
    Stores the validated output, never secrets and never the raw document."""
    __tablename__ = "ai_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"), default=None)
    operation: Mapped[str] = mapped_column(String, default="")
    provider: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    prompt_template_version: Mapped[str] = mapped_column(String, default="")
    requested_attributes: Mapped[list] = mapped_column(JSON, default=list)
    validated_output: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(default=None)
    latency_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String, default="OK")  # OK|UNAVAILABLE|INVALID_OUTPUT|ERROR
    created_at: Mapped[datetime] = mapped_column(default=_now)


class CisoSyncState(Base):
    """Tracks one push of a local verdict/gap into CISO Assistant. Not a queue —
    a status row for observability and manual retry (see app/ciso_sync.py)."""
    __tablename__ = "ciso_sync_state"
    __table_args__ = (UniqueConstraint("org_id", "local_entity_type", "local_entity_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    local_entity_type: Mapped[str] = mapped_column(String)  # evidence_control_link | gap
    local_entity_id: Mapped[str] = mapped_column(String)
    ciso_assistant_object_id: Mapped[str | None] = mapped_column(default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    last_sync_status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING|OK|FAILED|SKIPPED
    last_error: Mapped[str] = mapped_column(Text, default="")


class AuditEvent(Base):
    """Append-only. No route ever updates or deletes a row here.

    prev_hash/entry_hash are populated by app/audit_log.py so the chain can be
    verified; hash chaining is designed in from the start rather than retrofitted.
    """
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    # Explicit chain order. Timestamps can collide within the same microsecond and
    # ids are random, so ordering by them makes write-order and verify-order
    # disagree and the chain appear tampered with. seq is the single ordering key.
    seq: Mapped[int] = mapped_column(Integer, default=0, index=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), default=None)
    actor: Mapped[str] = mapped_column(default="")
    action: Mapped[str] = mapped_column(default="")
    entity_type: Mapped[str] = mapped_column(String, default="")
    entity: Mapped[str] = mapped_column(default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    before: Mapped[dict | None] = mapped_column(JSON, default=None)
    after: Mapped[dict | None] = mapped_column(JSON, default=None)
    request_id: Mapped[str] = mapped_column(String, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    prev_hash: Mapped[str] = mapped_column(String, default="")
    entry_hash: Mapped[str] = mapped_column(String, default="")
    at: Mapped[datetime] = mapped_column(default=_now)

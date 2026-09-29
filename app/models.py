"""All tables. One file — the slice's entity count doesn't earn a package.

Tenant-owned rows all carry org_id; see app/authorization.py for the access
rules and alembic/versions/*_rls.py for the Postgres row-level enforcement.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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
    role: Mapped[str] = mapped_column(String, default="CONTROL_OWNER")
    """Org-side: ORG_ADMIN|CONTROL_OWNER|COMPLIANCE_VIEWER. Firm-side:
    FIRM_ADMIN|AUDITOR — a FIRM_ADMIN staffs auditors onto engagements and
    decides onboarding requests; an AUDITOR only works the engagements it is
    staffed on. ORG_ADMIN is the compliance officer: org-wide visibility, owns
    remediation, is the auditee's voice to the firm. COMPLIANCE_VIEWER is the
    same visibility with every write path closed (Actor.can_write) — for a
    second-line reviewer, an external prep consultant, or a dashboard-only
    exec. See docs/adr/017-compliance-officer-persona.md."""


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


class OnboardingRequest(Base):
    """A prospective auditee asking a firm to audit it.

    Nothing tenant-owned exists until approval — approving is what creates the
    Organization and the Engagement, so a rejected request leaves no half-built
    org behind and a pending one is not yet a tenant. `frameworks` is what the
    client asked for; the firm decides what is actually allocated on approval.
    """
    __tablename__ = "onboarding_requests"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    audit_firm_id: Mapped[str] = mapped_column(ForeignKey("audit_firms.id"))
    org_name: Mapped[str]
    contact_email: Mapped[str] = mapped_column(default="")
    registration_detail: Mapped[str] = mapped_column(Text, default="")
    frameworks: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING|APPROVED|REJECTED
    decision_note: Mapped[str] = mapped_column(Text, default="")
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), default=None)
    engagement_id: Mapped[str | None] = mapped_column(ForeignKey("engagements.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_by: Mapped[str] = mapped_column(String, default="")


class EngagementAuditor(Base):
    """Which of a firm's auditors are staffed on which engagement.

    This is the access grant, not a label: belonging to the firm is not enough,
    a firm user with no row here sees that client in no list and cannot act
    under its engagement (app/auth.py builds the auditor Actor only if one
    exists). A FIRM_ADMIN is exempt — it is the role that does the staffing.
    """
    __tablename__ = "engagement_auditors"
    __table_args__ = (UniqueConstraint("engagement_id", "user_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    audit_firm_id: Mapped[str] = mapped_column(ForeignKey("audit_firms.id"))
    assigned_at: Mapped[datetime] = mapped_column(default=_now)
    assigned_by: Mapped[str] = mapped_column(String, default="")


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


class OrgCommitment(Base):
    """An org's own stated value for an organization-defined parameter, taken
    from its policy. What a requirement is actually tested against when the
    framework defers the threshold to the org (NIST 800-53's ODP pattern — see
    docs/adr/013-organization-defined-commitments.md): the framework says review
    access "on a recurring basis"; this row is what "recurring" means for THIS
    org, in their own words — so failing to meet it is the org failing its own
    stated commitment, not an externally-imposed number.

    One row per (org, attribute) — upserted whenever POLICY evidence extracts
    that attribute, unconditionally (app/service.py). Only the attributes a
    content pack actually references via org_defined_max_age_attribute are ever
    read back.
    """
    __tablename__ = "org_commitments"
    __table_args__ = (UniqueConstraint("org_id", "attribute"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    attribute: Mapped[str]
    value_json: Mapped[dict] = mapped_column(JSON, default=dict)  # {"v": <any>}
    source_evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    updated_at: Mapped[datetime] = mapped_column(default=_now)

    @property
    def value(self):
        return self.value_json.get("v")


# --------------------------------------------------------------------------- evidence

# Worker lifecycle. READY and the two terminal problem states end processing.
EVIDENCE_STATUSES = (
    "UPLOADED", "SCANNING", "STORED", "EXTRACTING", "ANALYZING",
    "EVALUATING", "READY", "FAILED", "NEEDS_REVIEW",
)

# Processing has stopped, for better or worse. Anything else means a job is
# either still running or died mid-run (see app/monitor.py's stuck detection).
TERMINAL_EVIDENCE_STATUSES = frozenset({"READY", "FAILED", "NEEDS_REVIEW"})


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

    # Human-entered metadata — never inferred, never required. A blank
    # description/valid_until is not a data-quality problem the pipeline should
    # flag; it just means nobody filled it in.
    description: Mapped[str | None] = mapped_column(Text, default=None)
    valid_until: Mapped[date | None] = mapped_column(default=None)
    # Detected at parse time (app/documents.py), not asked at upload — a user
    # can't know a PDF is password-protected until something tries to read it.
    is_encrypted: Mapped[bool] = mapped_column(default=False)
    # Soft delete only: evidence already reads as an append-only ledger
    # everywhere else (superseded, never overwritten), and a hard DELETE would
    # break FK-linked gaps/tasks/audit rows that still need to explain
    # themselves. Excluded from every read path below by deleted_at IS NULL.
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)
    deleted_by: Mapped[str | None] = mapped_column(default=None)

    links: Mapped[list["EvidenceControlLink"]] = relationship(back_populates="evidence")
    attributes: Mapped[list["EvidenceAttribute"]] = relationship(back_populates="evidence")

    def attribute_values(self) -> dict:
        """Just the values, for the evaluator.

        `extracted_attributes` stores the whole provenance-bearing field dict per
        attribute ({value, confidence, sources, ...}); `app/evaluate.py` wants a
        plain name -> value mapping. Lives here because the shape of that column
        is this model's business, not each caller's.
        """
        return {
            name: field.get("value") if isinstance(field, dict) else field
            for name, field in (self.extracted_attributes or {}).items()
        }


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

    # Auditor-only narration of the verdict above — never a second opinion, see
    # docs/adr/012-auditor-only-ai-nutshell.md. Empty when the model was
    # unavailable; the router omits this key entirely for a non-auditor caller.
    nutshell: Mapped[str] = mapped_column(Text, default="")
    nutshell_model: Mapped[str] = mapped_column(String, default="")
    nutshell_prompt_version: Mapped[str] = mapped_column(String, default="")

    # Set on every (re)evaluation. Compared against OrgCommitment.updated_at at
    # read time to flag a link whose org-defined ceiling has since changed —
    # see docs/adr/013-organization-defined-commitments.md. Not itself a
    # verdict input; purely a staleness signal for the payload.
    evaluated_at: Mapped[datetime] = mapped_column(default=_now)

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
    """A unit of remediation work. Two ways one comes to exist: the evaluator
    opens one per gap (`gap_id` set, status is evidence-driven — only new
    evidence can close it), or an org admin hands one straight to an employee
    (`gap_id` is None, status is closed by hand). `org_control_id` is an
    optional 'this is about that control' pointer, denormalized at creation
    time either way, so a manual task can still be scoped to a control an
    employee is or isn't allowed to see."""
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    gap_id: Mapped[str | None] = mapped_column(ForeignKey("gaps.id"), default=None)
    org_control_id: Mapped[str | None] = mapped_column(ForeignKey("org_controls.id"), default=None)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")  # only used when gap_id is None
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    due_at: Mapped[datetime | None] = mapped_column(default=None)
    priority: Mapped[str] = mapped_column(String, default="MEDIUM")  # LOW|MEDIUM|HIGH|CRITICAL
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN|DONE
    created_by: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)

    gap: Mapped[GapRow | None] = relationship(back_populates="tasks")


class ControlMessage(Base):
    """One shared thread per control for the auditor<->auditee conversation that
    isn't a deterministic verdict: 'please provide X' before any evidence exists,
    an auditee's request to reopen a locked control, or a plain comment. Kept as
    one table with a `kind` discriminator rather than three, since all three are
    the same shape (who said what, is it still open) — see
    docs/frontend-integration-blueprint.md's "Comments and attachments" note."""
    __tablename__ = "control_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    org_control_id: Mapped[str] = mapped_column(ForeignKey("org_controls.id"))
    kind: Mapped[str] = mapped_column(String)  # EVIDENCE_REQUEST|UNLOCK_REQUEST|COMMENT
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN|RESOLVED
    created_by: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)
    resolved_by: Mapped[str | None] = mapped_column(default=None)
    resolution_note: Mapped[str | None] = mapped_column(default=None)


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

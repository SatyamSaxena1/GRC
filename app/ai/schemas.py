"""What extraction produces. Every value is provenance-attached; a missing
attribute is null with no sources — never guessed."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Source(BaseModel):
    page: int | None = None
    quote: str = ""


class ExtractedField(BaseModel):
    value: Any = None
    confidence: float | None = None
    sources: list[Source] = []
    extraction_method: str = "none"  # native_text | vlm | none


class ExtractionRun(BaseModel):
    """One extraction call plus everything ai_run needs to explain it later."""
    fields: dict[str, ExtractedField] = {}
    model: str = ""
    provider: str = ""
    prompt_template_version: str = ""
    latency_ms: int = 0
    status: str = "OK"  # OK | UNAVAILABLE | INVALID_OUTPUT | ERROR


class AccessControlPolicy(BaseModel):
    """Canonical attribute contract for an access control policy.

    The extractor is driven by whatever attributes the content packs ask for, so
    this is the documented superset rather than a hard-coded requirement — it
    names the fields a policy artefact is expected to be able to supply.
    """
    document_title: Any = None
    document_type: Any = None
    version: Any = None
    issue_date: Any = None
    effective_date: Any = None
    approval_date: Any = None
    review_date: Any = None
    next_review_date: Any = None
    expiry_date: Any = None
    approver_name: Any = None
    approver_role: Any = None
    signature_present: Any = None
    scope_statement: Any = None
    entities_covered: list = []
    locations_covered: list = []
    systems_covered: list = []
    password_min_length: Any = None
    mfa_required: Any = None
    mfa_scope: list = []
    mfa_required_for: list = []
    access_review_frequency_days: Any = None
    privileged_access_controls: list = []
    logging_requirements: list = []
    encryption_at_rest: Any = None
    encryption_in_transit: Any = None
    log_retention_days: Any = None


class AccessReviewRecord(BaseModel):
    """Canonical attribute contract for an access-review record — proof a
    review actually happened, evaluated against the org's own policy-stated
    cadence rather than a generic ceiling (see
    docs/adr/013-organization-defined-commitments.md). Same documented-superset
    convention as AccessControlPolicy: the extractor only ever asks for what a
    content pack's required_attributes names."""
    last_access_review_date: Any = None
    reviewer_name: Any = None
    review_scope: Any = None
    accounts_reviewed_count: Any = None
    accounts_revoked_count: Any = None

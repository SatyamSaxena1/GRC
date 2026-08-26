"""End-to-end check against a real CISO Assistant instance. Skipped unless
CISO_ASSISTANT_BASE_URL/CISO_ASSISTANT_API_TOKEN are set, so CI stays green
without a running instance — run this before trusting the integration.

    CISO_ASSISTANT_BASE_URL=... CISO_ASSISTANT_API_TOKEN=... pytest tests/test_live_ciso_assistant.py -v
"""

from __future__ import annotations

import os

import pytest

from app.ciso_sync import CisoAssistantClient

pytestmark = pytest.mark.skipif(
    not (os.environ.get("CISO_ASSISTANT_BASE_URL") and os.environ.get("CISO_ASSISTANT_API_TOKEN")),
    reason="CISO_ASSISTANT_BASE_URL/CISO_ASSISTANT_API_TOKEN not set",
)


def test_client_authenticates_and_can_upsert_a_requirement_assessment():
    client = CisoAssistantClient()
    assert client.configured()
    object_id = client.upsert_requirement_assessment(
        external_id="live-check:smoke-test",
        payload={"framework": "ISO-27001", "clause": "A.5.15", "result": "COMPLIANT", "locked": True},
    )
    assert object_id

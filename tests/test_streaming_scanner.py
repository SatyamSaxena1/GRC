"""The incremental scanner behind live extraction results.

Its one safety property: it must never report a half-written value as a fact.
Everything it yields was accepted verbatim by json.loads — a value straddling a
chunk boundary waits rather than being guessed at.
"""

from __future__ import annotations

import json

import pytest

from app.ai.streaming import AttributeScanner, scan

FULL = {
    "password_min_length": {"value": 8, "confidence": 0.9,
                            "sources": [{"page": 6, "quote": "Minimum length: 8"}]},
    "approver_role": {"value": "CISO", "confidence": 1.0, "sources": []},
    "mfa_required": {"value": True, "confidence": 0.8, "sources": []},
    "missing_one": {"value": None, "confidence": 0.0, "sources": []},
}


def chunked(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


@pytest.mark.parametrize("size", [1, 2, 3, 7, 13, 64, 100_000])
def test_every_attribute_is_recovered_at_any_chunk_size(size):
    """Chunk boundaries fall in different places at each size — mid-key,
    mid-value, mid-escape. The result must not depend on where they land."""
    found = dict(scan(chunked(json.dumps(FULL), size)))
    assert found == FULL


def test_attributes_arrive_progressively_not_only_at_the_end():
    """The whole point: an attribute is reported as soon as its own value
    closes, long before the outer object does."""
    scanner = AttributeScanner()
    text = json.dumps(FULL)
    # feed everything except the final closing brace of the outer object
    got = []
    for chunk in chunked(text[:-1], 5):
        got.extend(scanner.feed(chunk))
    assert [name for name, _ in got] == list(FULL)


def test_a_partial_value_is_never_reported():
    scanner = AttributeScanner()
    assert scanner.feed('{"password_min_length": {"value": 8, "confi') == []
    # only once the value object closes does it count
    assert scanner.feed('dence": 0.9, "sources": []}') == [
        ("password_min_length", {"value": 8, "confidence": 0.9, "sources": []})
    ]


def test_braces_and_quotes_inside_strings_do_not_confuse_the_scanner():
    payload = {"quote_field": {"value": 'he said "}{" and left', "sources": []}}
    assert dict(scan([json.dumps(payload)])) == payload


def test_escaped_quotes_in_a_key_or_value_survive():
    payload = {"odd": {"value": 'a \\" b', "sources": []}}
    assert dict(scan([json.dumps(payload)])) == payload


def test_leading_prose_before_the_object_is_skipped():
    """Some models preface JSON with a sentence; the scanner starts at the
    first brace rather than failing."""
    text = 'Here is the JSON:\n' + json.dumps({"a": {"value": 1}})
    assert dict(scan([text])) == {"a": {"value": 1}}


def test_an_unparseable_entry_does_not_stop_later_ones():
    scanner = AttributeScanner()
    out = scanner.feed('{"bad": {"value": 0x}, "good": {"value": 3}}')
    assert ("good", {"value": 3}) in out

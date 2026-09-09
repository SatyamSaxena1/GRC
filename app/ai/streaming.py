"""Pull complete attributes out of a JSON object that is still being written.

The extraction prompt asks for `{"attr": {"value":..., "confidence":...,
"sources":[...]}, ...}`. A streamed response delivers that a few characters at
a time, so this scanner reports each top-level entry the moment its value is
syntactically closed — which is what lets the UI show `password_min_length = 8`
at ~4s instead of at ~27s when the whole object finally lands.

Deliberately a scanner, not a tolerant/repairing parser: it only ever yields
slices that are already valid JSON, so a half-written value can never be
reported as a fact. Whatever it yields, `json.loads` accepted verbatim.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Iterator

logger = logging.getLogger("app.ai.streaming")


class AttributeScanner:
    """Feed it chunks; it yields (name, value) per completed top-level entry.

    Stateful across chunks because a value routinely straddles a chunk
    boundary. Anything it cannot parse is skipped rather than guessed at.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._cursor = 0          # how far into the buffer we have consumed
        self._entered_object = False

    def feed(self, chunk: str) -> list[tuple[str, Any]]:
        self._buffer += chunk
        found: list[tuple[str, Any]] = []
        while True:
            entry = self._next_entry()
            if entry is None:
                return found
            found.append(entry)

    def _next_entry(self) -> tuple[str, Any] | None:
        """The next complete, parseable entry, or None when the buffer holds no
        more *complete* ones. An entry that is complete but malformed is
        skipped (cursor advanced past it) and scanning continues — one bad
        value must not strand every attribute behind it."""
        while True:
            buf = self._buffer

            if not self._entered_object:
                start = buf.find("{", self._cursor)
                if start == -1:
                    return None
                self._cursor = start + 1
                self._entered_object = True

            i = _skip_ws_and_commas(buf, self._cursor)
            if i >= len(buf) or buf[i] == "}":
                return None  # end of object, or nothing new yet
            if buf[i] != '"':
                return None  # key hasn't started arriving

            key_end = _end_of_string(buf, i)
            if key_end is None:
                return None  # key still mid-flight
            key = buf[i + 1:key_end]

            j = _skip_ws_and_commas(buf, key_end + 1)
            if j >= len(buf) or buf[j] != ":":
                return None
            j = _skip_ws_and_commas(buf, j + 1)
            if j >= len(buf):
                return None

            value_end = _end_of_value(buf, j)
            if value_end is None:
                return None  # value still mid-flight — wait for more chunks

            raw = buf[j:value_end + 1]
            self._cursor = value_end + 1
            try:
                return key, json.loads(raw)
            except json.JSONDecodeError:
                # Never guess. Skip it and keep scanning from just past it.
                logger.warning("streamed_attribute_unparseable key=%s", key)
                continue


def _skip_ws_and_commas(buf: str, i: int) -> int:
    while i < len(buf) and buf[i] in " \t\r\n,":
        i += 1
    return i


def _end_of_string(buf: str, start: int) -> int | None:
    """Index of the closing quote of the string starting at `start`, or None."""
    i = start + 1
    while i < len(buf):
        if buf[i] == "\\":
            i += 2
            continue
        if buf[i] == '"':
            return i
        i += 1
    return None


def _end_of_value(buf: str, start: int) -> int | None:
    """Index of the last character of the JSON value at `start`, or None if it
    is not complete yet."""
    ch = buf[start]
    if ch == '"':
        return _end_of_string(buf, start)
    if ch in "{[":
        closing = "}" if ch == "{" else "]"
        depth = 0
        i = start
        while i < len(buf):
            c = buf[i]
            if c == '"':
                end = _end_of_string(buf, i)
                if end is None:
                    return None
                i = end + 1
                continue
            if c == ch:
                depth += 1
            elif c == closing:
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return None
    # bare literal (number, true, false, null) — complete once a delimiter follows
    i = start
    while i < len(buf) and buf[i] not in ",}\r\n \t":
        i += 1
    return i - 1 if i < len(buf) else None


def scan(chunks: Iterable[str]) -> Iterator[tuple[str, Any]]:
    """Convenience wrapper for a finished iterable of chunks."""
    scanner = AttributeScanner()
    for chunk in chunks:
        yield from scanner.feed(chunk)

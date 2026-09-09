"""Ephemeral progress events for a pipeline run that a browser is watching.

**This is not the domain event bus ADR-009 defers, and must not become one.**
Nothing here is durable, ordered, replayable, or read by business logic. It
exists for one reason: extraction against a real document takes ~27s, of which
only ~3s is prompt processing, so a browser can watch facts appear as the model
produces them instead of staring at a spinner for half a minute.

The database stays the single source of truth. Every event published here is a
*preview* of something `app/service.py` will persist in the ordinary way when
the pipeline finishes. If a subscriber drops, or the process restarts, or this
module is bypassed entirely, nothing is lost — the client falls back to the
existing `GET /evidence/{id}/status` poll and reads the persisted result.

Single process only, exactly as ADR-006's in-process BackgroundTasks already
assume. A second worker process would simply see no subscribers and publish
into nothing, which degrades to today's polling behaviour rather than breaking.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import defaultdict
from typing import Iterator

logger = logging.getLogger("app.events")

# How long a subscriber waits for the next event before emitting a keep-alive,
# so a proxy (nginx, ngrok) doesn't time out an idle connection mid-extraction.
HEARTBEAT_SECONDS = 15.0

# Bounded so a subscriber that stops draining (a wedged browser tab) can never
# grow without limit; the publisher drops rather than blocks the pipeline.
MAX_QUEUED = 500

_lock = threading.Lock()
_subscribers: dict[str, list[queue.Queue]] = defaultdict(list)


def publish(key: str, event: str, data: dict) -> None:
    """Fan out to whoever is watching `key`. Never raises, never blocks the
    caller: this runs inside the evidence pipeline, and a slow or dead browser
    must not be able to stall or fail an upload."""
    with _lock:
        watchers = list(_subscribers.get(key, ()))
    for q in watchers:
        try:
            q.put_nowait((event, data))
        except queue.Full:  # pragma: no cover - only a wedged client hits this
            logger.warning("event_queue_full key=%s event=%s — dropping", key, event)


def subscribe(key: str) -> Iterator[tuple[str, dict]]:
    """Yield (event, data) until a `done` event arrives or the caller stops
    iterating. Yields ("ping", {}) on idle so the connection stays warm."""
    q: queue.Queue = queue.Queue(maxsize=MAX_QUEUED)
    with _lock:
        _subscribers[key].append(q)
    try:
        while True:
            try:
                event, data = q.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                yield "ping", {}
                continue
            yield event, data
            if event == "done":
                return
    finally:
        with _lock:
            watchers = _subscribers.get(key)
            if watchers and q in watchers:
                watchers.remove(q)
            if watchers is not None and not watchers:
                del _subscribers[key]


def has_subscribers(key: str) -> bool:
    """Whether anyone is watching — lets the pipeline skip the streaming code
    path entirely (and its extra bookkeeping) when nobody is looking."""
    with _lock:
        return bool(_subscribers.get(key))

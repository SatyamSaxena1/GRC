"""A ModelGateway that survives its primary model server going away.

The fast model sits behind a link that can drop (a peer machine that sleeps or
crashes, a model that unloads); the slower one sits on the host that is almost
always up. Wrapping the two means an upload during an outage is read by the second
model instead of landing in review with nothing extracted.

Rules, so the failover is never a way to hide a wrong answer:

* Provenance stays truthful. `model` / `provider` are the gateway that actually
  answered the latest call, and extraction re-reads them after the call, so the AI
  run on the evidence names the model that produced its facts.
* A call that fails on the primary is retried once on the secondary, and the
  primary is then treated as down *for this instance* (an instance lives for one
  pipeline run or one request), so a dead server costs one timeout, not one per call.
* Nothing is ever merged: one call, one model's answer.
* If neither is available the wrapper says so (`available()` is False) and the
  pipeline degrades exactly as it does with a single gateway: review, not guesswork.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("app.ai.failover")

_STATE = ("last_latency_ms", "last_stats", "last_truncated")


class FailoverGateway:
    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, secondary
        self._down: set[int] = set()       # ids of gateways that failed during this instance's life
        self._active = None
        self.failed_over = False

    # ------------------------------------------------------------------ selection
    def _usable(self, gateway) -> bool:
        return id(gateway) not in self._down and gateway.available()

    def _pick(self):
        if self._active is None or id(self._active) in self._down:
            self._active = next((g for g in (self.primary, self.secondary) if self._usable(g)), self.primary)
            if self._active is self.secondary:
                self.failed_over = True
                logger.warning("model_failover primary=%s -> secondary=%s",
                               getattr(self.primary, "model", "?"), getattr(self.secondary, "model", "?"))
        return self._active

    def _mark_down(self, gateway) -> None:
        self._down.add(id(gateway))
        self._active = None

    def _others(self, gateway):
        return [g for g in (self.primary, self.secondary) if g is not gateway and self._usable(g)]

    # ------------------------------------------------------------------ the gateway protocol
    @property
    def model(self) -> str:
        return getattr(self._pick(), "model", "")

    @property
    def provider(self) -> str:
        return getattr(self._pick(), "provider", "unknown")

    def available(self) -> bool:
        return self._usable(self.primary) or self._usable(self.secondary)

    def __getattr__(self, name):
        # last_latency_ms / last_stats / last_truncated describe the call that just ran
        if name in _STATE and "_active" in self.__dict__:
            return getattr(self._active or self.primary, name, {} if name == "last_stats" else 0)
        raise AttributeError(name)

    def _call(self, method: str, *args):
        gateway = self._pick()
        try:
            return getattr(gateway, method)(*args)
        except RuntimeError as exc:
            logger.warning("model_call_failed gateway=%s method=%s error=%s", getattr(gateway, "model", "?"), method, exc)
            self._mark_down(gateway)
            for other in self._others(gateway):
                self._active = other
                self.failed_over = self.failed_over or other is self.secondary
                try:
                    return getattr(other, method)(*args)
                except RuntimeError:
                    self._mark_down(other)
            raise

    def complete_json(self, system: str, user: str) -> str:
        return self._call("complete_json", system, user)

    def complete_vision(self, system: str, user: str, images: list[bytes]) -> str:
        return self._call("complete_vision", system, user, images)

    def next_token_logprobs(self, system: str, user: str, top: int = 20) -> dict[str, float]:
        return self._call("next_token_logprobs", system, user, top)

    def stream_json(self, system: str, user: str):
        """Stream from the active gateway; if it fails before producing anything, start over
        on the other. A failure *after* chunks were yielded propagates: extraction then
        discards the partial stream and makes one blocking call (which fails over properly)."""
        gateway = self._pick()
        started = False
        try:
            for piece in gateway.stream_json(system, user):
                started = True
                yield piece
            return
        except Exception as exc:  # noqa: BLE001 - any transport failure counts
            logger.warning("model_stream_failed gateway=%s started=%s error=%s", getattr(gateway, "model", "?"), started, exc)
            self._mark_down(gateway)
            if started:
                raise
        for other in self._others(gateway):
            self._active = other
            self.failed_over = self.failed_over or other is self.secondary
            streamer = getattr(other, "stream_json", None)
            if streamer is None:
                continue
            yield from streamer(system, user)
            return
        raise RuntimeError("no model server could stream this request")

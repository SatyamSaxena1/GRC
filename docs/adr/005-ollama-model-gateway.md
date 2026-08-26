# ADR-005: Local Ollama behind a ModelGateway interface

## Context
Evidence documents are confidential. Sending them to a hosted API is a data-residency
and confidentiality decision customers must make deliberately, not a default.

## Decision
Local Ollama by default, reached only through the `ModelGateway` protocol
(`app/ai/gateway.py`). The model name comes from `OLLAMA_MODEL` /
`OLLAMA_VISION_MODEL` and is never hard-coded. Business logic never touches the
provider's HTTP API.

## Alternatives considered
- **Hosted frontier model.** Materially better extraction, but unacceptable as a
  default for confidential evidence and unavailable for on-prem deployments.
- **Direct HTTP calls from the service layer.** Cheaper today, rewrites everything at
  the first provider change.

## Consequences
- Extraction quality is bounded by whatever local model is installed. A 7B model was
  observed returning different values across runs on the same document — which is
  exactly why ADR-004's split matters, and why auto-accept stays gated on the
  evaluation harness.
- The gateway degrades to null fields when the model is unavailable, never to guesses.
- Adding a provider means one new class implementing the protocol.
- Documents are never written to application logs; only identifiers and latencies are.

# ADR-053: An optional fallback model for the assistant

**Status:** Accepted
**Date:** 2026-11-06
**Deciders:** Platform owner ("keep OpenRouter a fallback")

## Context
The explain-why and Ask AI helpers use one OpenAI-style server: today LM Studio on the owner's machine, reached through a
tunnel. When the computer sleeps or the tunnel stops, the helper reads "offline". The owner also has a hosted option
(OpenRouter) and wants it kept as a fallback. The existing `LLM_FALLBACK` setting cannot do this: it only covers the
extraction path, and it names a second *kind* of provider (Ollama versus OpenAI-style), so two OpenAI-style servers cannot
back each other up. The tool-calling gateway has no fallback at all.

## Decision
Set `LLM_FALLBACK_BASE_URL` (and `LLM_FALLBACK_MODEL`, `LLM_FALLBACK_API_KEY`, optionally `LLM_FALLBACK_REASONING_EFFORT`).
Per request, if the primary server is not reachable (or does not list its model), the helper uses the fallback, but only if
that is reachable; if both are down it reports offline as before.
- The fallback has its **own key**; the primary's key is never sent to it. Reasoning effort is not sent to it unless asked
  (a hosted server may reject it).
- It is chosen **per request, before the call**. A call that fails midway on a reachable primary is not retried elsewhere.
- The audit record already names the model that answered, so an answer from the fallback is visible as such.

## Options Considered
### Option A: Choose the gateway by reachability per request (chosen)
Complexity low (one function and two constructor options); no behaviour change when unset; costs one short availability check
per request. **Cons:** no retry on a mid-call failure.
### Option B: Retry on failure through the existing failover wrapper
The wrapper retries on a `RuntimeError`, but the tool loop never raises (it returns what it has), and the wrapper does not
carry the tool method. Making it do so is a larger change to a shared class for the same practical benefit.
### Option C: Do nothing, switch by hand
Zero code, but the helper stays offline until a person edits settings and redeploys.

## Trade-off Analysis
Reachability is exactly what fails in practice (a sleeping computer, a stopped tunnel), so Option A covers the real
outage case cheaply and leaves the shared failover class alone.

## Consequences
- Easier: the helper stays up when the home computer is off, at the free tier's request limits.
- Harder: two sets of settings to keep valid; free hosted models have daily limits and may lack some features, so check the
  model's `supported_parameters` (tools, response_format) before relying on it.
- Not covered: the extraction/OCR path still uses `LLM_FALLBACK` (a different provider *kind*).

## Action Items
1. [x] `LMStudioGateway` takes its own key and reasoning setting; `_tool_gateway()` picks by reachability.
2. [x] Tests: primary used when up, fallback when down, own key only, no reasoning effort by default.
3. [ ] Operator: add the three `LLM_FALLBACK_*` settings in Render and redeploy.

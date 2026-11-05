# Giving the AI helper a stable address (issue #84)

Today the helper reaches a model on a personal machine through a temporary tunnel. That is for demos only.
The app needs no code change to use a stable model: it reads settings.

## Settings (Render environment, or any host)
| Setting | Meaning |
|---|---|
| `LLM_PROVIDER=openai` | use the OpenAI-style chat API client |
| `LLM_BASE_URL` | the model server's address |
| `LLM_API_KEY` | its key, held as a secret and never committed |
| `LLM_MODEL` | the model name |
| `LLM_REASONING_EFFORT` | `none` by default; set empty if the server rejects it |

The sidebar light shows whether the backend can reach the model, so a wrong setting is visible straight away.

## Decision: a hosted model API
Chosen on 2026-11-05 for a stable, authenticated address. Two things change and must be said plainly:

1. **Data leaves your hardware.** The local-model setup kept document text on your own machine. With a hosted API,
   the text the helper is asked about goes to that vendor under their terms. Do not turn it on for a customer who
   has not agreed to that, and say so in their contract.
2. **The architecture rule is unchanged.** The model only phrases or extracts. Fixed, versioned rules decide every
   verdict, and a named human signs and locks (ADR-004). A different model changes wording, never a verdict.

## Not yet verified
The client sends `response_format` (json_schema), `reasoning_effort` and `seed`. Some hosted servers reject or
ignore them. Before relying on one, try it on a throwaway deployment with the sidebar light and one Explain request,
and set `LLM_REASONING_EFFORT=` (empty) if it answers HTTP 400. Nothing here has been tried against a hosted
vendor yet, so issue #84 stays open until that check passes.

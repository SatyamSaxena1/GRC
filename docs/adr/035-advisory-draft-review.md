# ADR-035: Advisory help for reviewing drafted pack requirements

> **Status:** Proposed. Implemented: `tools/review_assist.py`, the `--assist` flag of
> `python -m tools.review_drafts`, `tests/test_review_assist.py`.

## Context
The source-text pipeline (ADR-034) has a model draft one requirement per provision and a person
accept, edit or reject each. A reviewer working through hundreds of drafts has to notice, from the
law's text alone, where a draft says more or less than the law does. Could a model help, using
retrieval?

## Decision
Yes, as advice, shown beside the draft and labelled as such. Three layers, in order of trust:

1. **Mechanical checks, no model.** The source text is unchanged since drafting; the quoted text is
   the law's own words; a number in a condition is written in the provision (or flagged as derived);
   no new artefact type is slipped in; the clause is not already in the pack.
2. **Related provisions fetched by id, no embeddings.** The provisions the text cites ("Article
   6(1)") and the paragraphs on either side, capped in number and length, listed by reference so the
   reviewer knows what the model was shown. The sources are already parsed into addressable
   provisions, so this is a lookup: it cannot return the wrong passage, only miss one.
3. **A sceptical critique from the model.** It is told to argue against the draft, to use only the
   text given, to say "cannot tell" rather than recall the law from memory, and to cite provisions.
   It returns whether the draft is faithful to the text and lists of concerns, missing context and
   suggested changes. Output that cannot be parsed is shown as unavailable, never guessed at.

**The critique has no power.** Nothing reads it except the display. It never accepts, rejects or edits
a draft, and a "no" does not block acceptance any more than a "yes" grants it (ADR-004: a model never
decides; ADR-026: a model's review is evidence, not approval). Tests assert both directions and that
the draft is byte-identical afterwards.

The critique is stored on the draft entry (`assist`, keyed by source hash, critic-prompt hash and
model) so a session does not re-ask the model or lose the advice. Mechanical checks are recomputed
each time, because they are cheap and the pack may have changed.

## Why not vector retrieval
The reviewer's question is about one provision and what it points at, and the structure already
answers it. Similarity search would help with "which other articles bear on this one" across a whole
law, which is a real but smaller job; ADR-002 keeps pgvector as the place it would live if it is ever
needed.

## Trade-offs
- A model tends to agree with its own drafts. `REVIEW_ASSIST_MODEL` selects a different reviewer
  model, and the view says when the reviewer is the drafter.
- A model that has read the law in training may import detail the text does not contain. The prompt
  forbids it and asks for "cannot tell", but that is an instruction, not a guarantee.
- Cited-by-id retrieval follows "Article N" references only. Recitals, annexes and references phrased
  without that pattern are not fetched.
- Advice can anchor a tired reviewer. It is shown after the draft and labelled advisory for that reason.

## Measured (EU AI Act drafts Art. 4, 5(2), 26(1), LM Studio, 2026-11)
Same prompt, three reviewers. Prompts were 700 to 1,600 tokens, so the 116k-token context window of the
loaded model was never a factor and no call was truncated.

| Reviewer | Time per draft | Output tokens | What it did |
|---|---|---|---|
| gemma-4-e4b (the drafter), reasoning off | 1 to 3 s | about 300 | Found the Art. 4 over-reach, but faulted drafts for what the adjacent paragraph says and once rated a draft "faithful" while listing such a concern |
| qwen3.5-9b, reasoning off (`LLM_REASONING_EFFORT=none`, the default) | 4 to 5 s | 320 to 380 | More substantive, mostly about the provision's own text: "the law requires measures be taken, not that they be documented" is exactly the documentable-or-not question |
| qwen3.5-9b, reasoning on (server default) | 60 to 100 s | 5,000 to 8,500 | No clearer; on Art. 5(2) it brought in requirements (FRIA, registration) that are not in the provision |

So: use `REVIEW_ASSIST_MODEL=qwen/qwen3.5-9b` with reasoning off. Thinking costs 15 to 20 times as long
and did not improve the critique. This is five drafts by eye, not a measurement of how often a bad
draft is caught; the neighbour tagging stays on for every reviewer.

## Not covered
Reviewing edits as well as drafts, checking mappings to unified control objectives for plausibility,
cross-law conflicts, and measuring whether the critique actually catches bad drafts (that needs a set
of drafts with known defects).

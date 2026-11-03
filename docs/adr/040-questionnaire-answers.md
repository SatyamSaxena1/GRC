# ADR-040: Security questionnaire answers

Status: accepted

## Context
Customers send security questionnaires, and answering them means searching the workspace by hand. The
assistant could answer in free text, but a model asked "do you enforce MFA?" will happily say yes.

## Decision
`POST /questionnaire/answer` takes one question and returns a status, a draft answer and the controls it rests on.
- **Matching is deterministic.** Words in the question (plus a short synonym list: MFA, offboarding, logs,
  pull request) are compared with each visible control's title, text and clause. A control matches on a
  shared word in its title, or at least two shared words overall.
- **The status is decided from verdicts alone**: no match is NOT_EVIDENCED; any failing control is NO; all
  passing is YES; a mix with at least one pass or partial is PARTIAL. An auditor-locked control counts by
  its folded verdict and is flagged as reviewed.
- **A model only words the answer**, when one is online. It sees the status and the matched controls, must
  reply in two sentences or fewer as JSON, and is discarded for the rules' own sentence if the reply is
  unusable, over long, or opens with a word that contradicts the status. It is not called at all when
  nothing matched, so it cannot invent support.
- With no model, the page still answers, in the rules' sentence.
- One question per request so a slow model cannot time out a whole questionnaire; the page fills answers
  in as they arrive and exports a CSV.
- The audit log records that a question was answered, the status and counts, never the question text, which
  can name a customer.

## Consequences
- These are drafts. Matching is by words, so an unusual phrasing can miss; it then answers NOT_EVIDENCED
  rather than guessing, which is the safe failure.
- Answers reflect the workspace today; they are not a signed attestation.
- Synonyms are a small hand-kept list; extending it is a one-line change.

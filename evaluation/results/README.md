# Evaluation results

One JSON (and the console log) per run of `python -m evaluation.runner --save`.

**20261006-134747-google_gemma-4-e4b** is the reliability baseline taken before any
prompt or retrieval changes: 11 documents (2 labelled + 9 demo samples), 3 repeats each,
33 extraction runs, `google/gemma-4-e4b` over LM Link, temperature 0, seed 42, num_ctx 16384.

It is **not** the production model (`qwen2.5vl:7b`); it is the reference to compare later
changes against *on the same model*. Weak spot: `access_review_frequency_days` (75%) -
the same document returns nothing, nothing, then `["quarterly","annually"]`. Cited page
numbers on single-page text files are also unreliable (the model says page 2).

Re-run a comparison with the same flags; a change ships only if accuracy rises with no
regression over >=3 repeats. A run aborts with "model unreachable" rather than scoring blanks.

# GRC reviewer on ReviewBench (offline)

This runs the Phase 2 model reviewer (`app/review/agent.py`) as a
[ReviewBench](https://github.com/review-bench/ReviewBench) agent: one container per pull
request, following its `AGENT_CONTRACT.md`. It is for offline tuning. Only a final run through
the ReviewBench portal can appear on the leaderboard, and offline numbers with a different judge
are **not** comparable with the leaderboard.

The reviewer:
- reads `/work/pr/diff.patch`;
- reads and searches the checkout through **read-only tools that cannot leave `/work/repo`**;
- calls your model;
- writes `findings.json`.

It has no network tools of its own, so it cannot look the answers up on GitHub.

## 1. Serve the model
LM Studio: load **Qwen3.8-27B**, start the server (Developer tab, port 1234), and note the model
id it shows (for example `qwen/qwen3.8-27b`). Give it a context of at least 32k tokens; diffs are
sent in chunks of about 24k characters, plus whatever the model reads through the tools.

## 2. Build the image (from the GRC repository root)
```sh
docker build -f bench/reviewbench/Dockerfile -t grc-reviewer:dev .
```

## 3. Produce findings
Use WSL or Git Bash on Windows: `try-agent.sh` needs bash, docker, git and jq.
```sh
git clone https://github.com/review-bench/ReviewBench && cd ReviewBench && npm ci
export RB_MODEL_BASE_URL=http://host.docker.internal:1234/v1   # LM Studio on this machine
export RB_CONFIG_MODEL=qwen/qwen3.8-27b                       # the id LM Studio shows
export RB_CONFIG_MODE=agent                                    # agent | rules | both
root=$PWD run=$PWD/runs/grc-qwen-$(date +%Y%m%d-%H%M%S) && mkdir -p "$run"
cd "$run" && TRY_AGENT_WORK=$root/.try-agent "$root/scripts/try-agent.sh" grc-reviewer:dev --pr 0 \
  -e RB_MODEL_BASE_URL -e RB_CONFIG_MODEL -e RB_CONFIG_MODE      # one PR first
TRY_AGENT_WORK=$root/.try-agent "$root/scripts/try-agent.sh" grc-reviewer:dev \
  -e RB_MODEL_BASE_URL -e RB_CONFIG_MODEL -e RB_CONFIG_MODE      # the 25-PR test set
```
Each PR's log line ends with `chunks=… calls=… tool_calls=… kept=… dropped=…` and
`findings=… seconds=…`. The benchmark allows 15 minutes per PR; the reviewer stops starting
new chunks at 13.

## 4. Judge
- **Comparable with the leaderboard**: the leaderboard's judge is Claude Sonnet 5 (see
  ReviewBench `docs/OFFLINE_EVAL.md` for its `models.json`).
  ```sh
  export ANTHROPIC_API_KEY=...
  npm run judge -- --candidate "$run/findings" --provider anthropic --model claude-sonnet-5 \
    --output "$run/scoring/results.json" --concurrency 4
  ```
- **Free, local, for tuning only**: Qwen judging Qwen is biased toward its own findings. Use it
  to compare prompt or configuration changes against each other, never against the
  leaderboard. Add LM Studio as an OpenAI-compatible provider in a `models.json` (see the pi
  models documentation linked from ReviewBench `docs/JUDGING.md`) and pass
  `--provider <that name> --model qwen/qwen3.8-27b`.

Read `results.json` for **grounded** precision and recall. The methodology warns against
ranking on augmented recall. Record the judge provider and model, the image digest,
`RB_CONFIG_MODEL` and `RB_CONFIG_MODE` with every result; `results.json` stores the judge and
the corpus hashes.

## What we measured here
With `RB_CONFIG_MODE=rules`, all 25 test PRs ran and passed the contract checks
(`passed 25, failed 0`). That proves the image and the findings format. The rules found 5
things, all likely false positives for review purposes: credentials in test fixtures, a README
example, and PEM header constants in a key parser. That is why the default mode is `agent`, and
why the secret rule may need test and doc excludes for code review.

No model has been run against the corpus from here. Running Qwen needs your LM Studio.

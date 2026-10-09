# Running the typed decisions on a Jev-class model

Three features ask a model to choose one option: the upload form's type suggestion and the
wrong-document guard, the quote-support check, and the rights-request kind suggestion. By
default the extraction model answers them. A small Jev-class decision model can answer them
instead (ADR-025). The JevBench leaders that run on one GPU include H2O-Lightning-4B v1.1 and
decider-12b v2.

## 1. Serve the model
The model must return next-token log-probabilities. Either of these works:
- **Ollama 0.12.11 or later.** Import the model's GGUF with a Modelfile (`ollama create <name> -f Modelfile`).
- **vLLM, llama.cpp server or LM Studio.** Serve it through the OpenAI-compatible API, with
  logprobs enabled.

## 2. Measure it against today's model
```
python -m evaluation.decisions --model qwen2.5vl:7b --model <name> --save
```
Add `--provider openai --base-url http://<host>:8000` for an OpenAI-compatible server.

Look at four things:
- accuracy and calibration;
- **order-dependent**: answers that change with the option order, which production discards;
- the **guard** lines: what the wrong-document guard and the quote check would catch, and
  falsely flag, at today's thresholds.

Put the table in ADR-025.

## 3. Switch it on
| Setting | Value |
|---|---|
| `LLM_DECISION_MODEL` | the model name |
| `LLM_DECISION_PROVIDER` | `ollama` or `openai`. Defaults to `LLM_PROVIDER` |
| `LLM_DECISION_BASE_URL` | the server, if it is not the extraction server |

No deploy is needed. To roll back, unset `LLM_DECISION_MODEL`. If the decision server goes
down, the extraction model answers instead, and each AI run records which model it was.

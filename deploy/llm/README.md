# Self-hosted LLM host

Ollama on a GPU machine, fronted by Caddy (TLS + bearer token). The GRC app on
Render calls it over HTTPS; document text and page images go nowhere else.

## Sizing
- ≥ 24 GB VRAM (RTX 4090 / A5000 class) keeps `qwen2.5vl:7b` (~6 GB) and an ~8B
  text model resident together. A 12–16 GB card works if you keep one model loaded
  (`OLLAMA_MAX_LOADED_MODELS=1` — expect a reload pause when users switch models).
- ~30 GB disk for models and image layers.

## Set up
1. Install Docker and the NVIDIA Container Toolkit; check `docker run --rm --gpus all ubuntu nvidia-smi`.
2. Point `LLM_DOMAIN` (DNS A record) at the machine. Open 80/443 only; keep 11434 closed.
3. `cp .env.example .env`, pin `OLLAMA_VERSION`, set `OLLAMA_API_KEY` (`openssl rand -hex 32`).
4. `docker compose up -d` — `model-pull` downloads the models, then exits.
5. From anywhere: `curl -H "Authorization: Bearer $OLLAMA_API_KEY" https://$LLM_DOMAIN/api/tags`
   lists the models; without the header it must return 401.
6. In Render's `grc-secrets` group set `OLLAMA_BASE_URL=https://<LLM_DOMAIN>` and the same `OLLAMA_API_KEY`.

## Running on your own PC (Tailscale Funnel — no card, no domain)
Use `docker-compose.pc.yml` instead: nothing is exposed on your network, the PC
only makes an outbound connection, and Tailscale's free plan needs no payment
method — you sign in with an existing Google/Microsoft/GitHub account.

1. Docker Desktop (WSL2 backend) and a current NVIDIA driver; check
   `docker run --rm --gpus all ubuntu nvidia-smi`.
2. `.env`: pin `OLLAMA_VERSION`, set `OLLAMA_API_KEY`, `MODELS`. No domain and no
   token needed. Keep `OLLAMA_MAX_LOADED_MODELS=1` on 12–16 GB cards.
3. `docker compose -f docker-compose.pc.yml up -d`.
4. One-time interactive login — this is the only manual step:
   ```
   docker compose -f docker-compose.pc.yml exec tailscale tailscale up --qr
   ```
   Open the printed URL (or scan the QR code) and sign in. No card is asked for
   on Tailscale's free tier.
5. Turn the container's local port 80 into a public HTTPS URL:
   ```
   docker compose -f docker-compose.pc.yml exec tailscale tailscale funnel 80
   ```
   This prints the public URL, `https://grc-llm.<your-tailnet>.ts.net`. That is
   your `OLLAMA_BASE_URL`. It stays the same across restarts once set.
6. Verify: `curl -H "Authorization: Bearer $OLLAMA_API_KEY" https://grc-llm.<your-tailnet>.ts.net/api/tags`
   lists the models; without the header it must return 401.
7. In Render's `grc-secrets` group set `OLLAMA_BASE_URL` to that URL and the
   same `OLLAMA_API_KEY`.
8. The site only gets AI extraction while the PC is on, awake and online — turn off
   sleep/hibernate. When it is off the app keeps working with null-field extraction.

## Adding a security-tuned model
`MODELS` takes any Ollama-pullable reference, including Hugging Face GGUFs
(`hf.co/<org>/<repo>:<quant>`). A security-tuned 8B instruct model (for example
Cisco's Foundation-sec-8B family) is the intended candidate — **confirm the exact
repo, quant tag and licence before adding it; they are not pinned here.**

It is text-only. Users select it as the per-evidence model in the upload form
(`GET /evidence/ai-models` lists whatever is pulled); the vision model stays
`qwen2.5vl:7b`. Before offering it to customers, run against this host:

    OLLAMA_BASE_URL=https://<LLM_DOMAIN> OLLAMA_API_KEY=... \
    OLLAMA_MODEL=<its tag> pytest tests/test_live_ollama.py

The extraction prompt needs strict JSON with provenance, and small models drift.
Verdicts are computed deterministically (ADR-004), so a weaker model lowers
extraction quality but cannot produce a false pass.

## Keeping it self-contained
- Models are pulled once at provisioning; afterwards firewall outbound traffic
  except what Let's Encrypt needs, or pre-load models and run without egress.
- Restrict 443 to Render's outbound IPs (Render dashboard → service → Networking)
  in addition to the bearer token.
- If this host is down the app degrades to null-field extraction and keeps
  serving; `app.monitor` retries damaged runs once it returns.

## Use the Ollama already on your PC (no Docker)
If Ollama is already installed and has the model, you do not need the Docker recipes above.
`windows/ollama_gate.py` puts a token check in front of it, and Tailscale Funnel publishes
the gate. Only Tailscale needs installing; the gate uses packages the repo already has.

1. Install Tailscale for Windows and sign in (free plan, no card). Funnel must be enabled for
   your tailnet once (the first `tailscale funnel` tells you how).
2. In `deploy/llm/.env` set `OLLAMA_API_KEY` (`openssl rand -hex 32`). Keep Ollama on
   loopback: turn **off** "Expose Ollama to the network" in its settings and restart it.
3. Start the gate: `powershell -ExecutionPolicy Bypass -File deploy\llm\windows\start-gate.ps1`
   (listens on `127.0.0.1:8088` only; it warns if Ollama is exposed on all interfaces).
4. Publish it, once: `tailscale funnel --bg 8088`. It prints `https://<pc>.<tailnet>.ts.net`.
5. Verify from anywhere: without the header `curl https://<that>/api/tags` must return 401;
   with `-H "Authorization: Bearer $OLLAMA_API_KEY"` it lists the models. A `DELETE`/`pull`
   must return 403 even with the token.
6. In Render set `OLLAMA_BASE_URL=https://<that address>` and the same `OLLAMA_API_KEY`
   (copy it from the file into Render directly; do not paste it into chat or commit it).

What to expect: the PC must be on, awake and signed in with Ollama and the gate running.
Ollama handles one request at a time per model by default, so visitors uploading together
queue (Render waits up to `OLLAMA_TIMEOUT_S`, 180s). If the PC is off the site keeps serving
and uploads read "analysis model was unavailable" until it is back, then Re-run analysis.
Tailscale Funnel does not decrypt the traffic; TLS ends on your PC.


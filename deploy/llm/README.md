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

## Running on your own PC (Cloudflare Tunnel)
Use `docker-compose.pc.yml` instead: nothing is exposed on your network, and the
PC only makes an outbound connection.

1. Docker Desktop (WSL2 backend) and a current NVIDIA driver; check
   `docker run --rm --gpus all ubuntu nvidia-smi`.
2. A domain managed in Cloudflare (free plan is fine). In Zero Trust →
   Networks → Tunnels, create a tunnel, copy its token into `TUNNEL_TOKEN`, and add
   a public hostname such as `llm.<yourdomain>` with service `http://caddy:80`.
3. `.env`: pin `OLLAMA_VERSION`, set `OLLAMA_API_KEY`, `MODELS`, `TUNNEL_TOKEN`.
   Keep `OLLAMA_MAX_LOADED_MODELS=1` on 12–16 GB cards.
4. `docker compose -f docker-compose.pc.yml up -d`, then run the `curl` check from
   step 5 above against `https://llm.<yourdomain>`.
5. The site only gets AI extraction while the PC is on, awake and online — turn off
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

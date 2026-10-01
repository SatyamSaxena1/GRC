"""Token-checking front door for the Ollama already running on this PC.

Ollama has no login of its own. Publish it (Tailscale Funnel, a tunnel, anything) and
anyone who finds the address can run your models, or pull and delete them. This sits in
front instead: it listens on loopback only, rejects any request without the bearer token
(401), and then only forwards the two calls the GRC app makes (app/ai/ollama.py), so even
a leaked token cannot pull, delete, create or push models (403).

    set OLLAMA_API_KEY=<64 hex chars>      (start-gate.ps1 reads it from ../.env)
    python ollama_gate.py                   -> http://127.0.0.1:8088
    tailscale funnel --bg 8088              -> the public https://....ts.net address

Uses packages the repo already installs (fastapi, uvicorn, httpx); nothing else to install.
"""
import hmac
import os
import sys

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

UPSTREAM = os.environ.get("OLLAMA_UPSTREAM", "http://127.0.0.1:11434")
PORT = int(os.environ.get("GATE_PORT", "8088"))
KEY = os.environ.get("OLLAMA_API_KEY", "")
# Exactly what the app calls. Anything else (pull, delete, create, push, copy, show...) is refused.
ALLOWED = {("GET", "/api/tags"), ("POST", "/api/chat")}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
# A cold vision model can take minutes to produce its first token (Caddy's recipe uses 300s too).
client = httpx.AsyncClient(base_url=UPSTREAM, timeout=httpx.Timeout(300.0, connect=5.0))


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def gate(path: str, request: Request):
    if not hmac.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {KEY}".encode()):
        return Response(status_code=401)
    if (request.method, "/" + path) not in ALLOWED:
        return Response(status_code=403)
    upstream = await client.send(
        client.build_request(
            request.method, "/" + path, content=await request.body(),
            headers={"content-type": request.headers.get("content-type", "application/json")},
        ),
        stream=True,
    )
    # Raw bytes straight through, so token streaming is not buffered.
    return StreamingResponse(
        upstream.aiter_raw(), status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"), background=BackgroundTask(upstream.aclose),
    )


if __name__ == "__main__":
    if len(KEY) < 32:
        sys.exit("OLLAMA_API_KEY must be set to a long random value (at least 32 characters).")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")  # loopback only, on purpose

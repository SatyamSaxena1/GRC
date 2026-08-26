from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.ollama import OllamaGateway
from app.db import engine, init_db
from app.routers import admin, analytics, audit, ciso, controls, evidence

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app")

DEBUG = os.environ.get("DEBUG", "").lower() in {"1", "true", "yes"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="GRC vertical slice", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """One request id on every log line and response. Document contents are never
    logged — only identifiers."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logger.info("request method=%s path=%s status=%s request_id=%s",
                request.method, request.url.path, response.status_code, request_id)
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Never leak a stack trace to a caller in production."""
    request_id = getattr(request.state, "request_id", "")
    logger.exception("unhandled_error request_id=%s", request_id)
    detail = repr(exc) if DEBUG else "internal server error"
    return JSONResponse(status_code=500, content={"detail": detail, "request_id": request_id})


app.include_router(admin.router)
app.include_router(evidence.router)
app.include_router(audit.router)
app.include_router(controls.router)
app.include_router(controls.gaps_router)
app.include_router(controls.tasks_router)
app.include_router(analytics.router)
app.include_router(ciso.router)


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    """Readiness reflects real dependencies; the model being down is degraded,
    not dead, because evaluation still runs deterministically without it."""
    checks = {}
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"

    gateway = OllamaGateway()
    checks["model"] = "ok" if gateway.available() else "unavailable"
    checks["model_name"] = gateway.model or "unconfigured"

    ready_ = checks["database"] == "ok"
    return JSONResponse(status_code=200 if ready_ else 503,
                        content={"ready": ready_, "checks": checks})

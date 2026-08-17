"""
main.py — Dev Bridge FastAPI application.

Core surface: loopback HTTP + WebSocket chat + PTY.
Optional extras (orchestrator, cockpits, employee, …) are included as routers.

Pump architecture (mid-turn steering)
--------------------------------------
Each WS connection has ONE persistent "pump" task that drains the session's
out_queue → ws.send_text() for the WS lifetime.  The pump never breaks on
AiDone/AiError — it forwards them and keeps running.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from devscope_bridge.local_env import load_local_env

load_local_env()

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from devscope_bridge import browser_relay
from devscope_bridge import capability_router
from devscope_bridge import session_manager
from devscope_bridge import session_store
from devscope_bridge import watchdog_medic
from devscope_bridge.bridge_auth import (
    BRIDGE_DIR,
    generate_and_persist_token,
    require_auth,
    extract_token as _extract_token,
    check_auth as _check_auth,
    validate_session_name as _validate_session_name,
    ws_auth as _ws_auth,
)
from devscope_bridge.models import HealthResponse
from devscope_bridge.pty_ws import router as pty_router
from devscope_bridge.session_http import router as session_http_router
from devscope_bridge.ws_session import (
    router as ws_router,
    _command_queue,
    _handle_session_command,
    _parse_command_target,
    _pump_frames,
    _resolve_out_queue,
    _session_pumps,
    _silence_seconds,
    _start_session_pump,
    _ws_receive_loop,
)

logger = logging.getLogger(__name__)

_startup_token: str = ""
_start_time: float = 0.0

# Aliases for tests that patch these directly on this module
_active_ws = browser_relay._active_ws
_pending_actions = browser_relay._pending_actions

_generate_and_persist_token = generate_and_persist_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_token, _start_time
    _startup_token = generate_and_persist_token()
    _start_time = time.time()
    from devscope_bridge import task_store
    task_store.init_db()
    cleared = session_store.repair_duplicate_session_ids()
    if cleared:
        logger.info("Repaired duplicate session_ids: %s", cleared)
    from devscope_bridge import orchestrator
    from devscope_bridge.session_runner import BridgeSessionRunner
    if os.environ.get("ORCHESTRATOR_ENABLED", "1") == "1":
        orchestrator.start_loop(BridgeSessionRunner())
        logger.info("orchestrator loop enabled")
    from devscope_bridge import session_hygiene
    session_hygiene.start_background_loop()
    logger.info("session hygiene loop enabled")
    asyncio.create_task(session_hygiene.run_hygiene_pass())
    session_manager.start_stale_turn_sweeper()
    from devscope_bridge.whatsapp import cockpit_poller
    poller_task = asyncio.create_task(cockpit_poller.run_forever())
    logger.info("cockpit poller started")
    from devscope_bridge.meta_ads import meta_ads_poller
    meta_poller_task = asyncio.create_task(meta_ads_poller.run_forever())
    logger.info("meta ads poller started")
    print(f"\nDev Bridge started. Token: {_startup_token}\n")
    logger.info("Dev Bridge ready on 127.0.0.1:7878")
    yield
    logger.info("Dev Bridge shutting down")
    poller_task.cancel()
    meta_poller_task.cancel()
    from devscope_bridge import orchestrator, session_hygiene
    await orchestrator.stop_loop()
    await session_hygiene.stop_background_loop()
    await session_manager.stop_stale_turn_sweeper()


_extension_id = os.environ.get("BRIDGE_EXTENSION_ID", "chrome-extension://EXTENSION_ID_PLACEHOLDER")
_cors_origins = [_extension_id, "http://localhost", "http://127.0.0.1"]

app = FastAPI(title="Dev Bridge", version="0.1", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Core: chat sessions, browser actions, WS, PTY
app.include_router(session_http_router)
app.include_router(ws_router)
app.include_router(pty_router)

# Optional extras — personal add-ons, not the public product surface
from devscope_bridge import task_routes
from devscope_bridge import orchestrator_routes
app.include_router(task_routes.router, dependencies=[Depends(require_auth)])
app.include_router(orchestrator_routes.router, dependencies=[Depends(require_auth)])

from devscope_bridge.schedule_routes import router as schedule_router
app.include_router(schedule_router, dependencies=[Depends(require_auth)])

from devscope_bridge.whatsapp_routes import router as wa_router
app.include_router(wa_router, dependencies=[Depends(require_auth)])

from devscope_bridge.whatsapp.cockpit_routes import router as cockpit_router
app.include_router(cockpit_router, dependencies=[Depends(require_auth)])

from devscope_bridge.gmail_routes import router as gm_router
app.include_router(gm_router, dependencies=[Depends(require_auth)])

from devscope_bridge.calendar_routes import router as cal_router
app.include_router(cal_router, dependencies=[Depends(require_auth)])

from devscope_bridge.meta_ads_routes import router as meta_router
app.include_router(meta_router, dependencies=[Depends(require_auth)])

from devscope_bridge.invoke_routes import router as invoke_router
app.include_router(invoke_router, dependencies=[Depends(require_auth)])

from devscope_bridge.employee_routes import router as employee_router
app.include_router(employee_router, dependencies=[Depends(require_auth)])

from devscope_bridge.plugin_store_routes import router as store_router
app.include_router(store_router, dependencies=[Depends(require_auth)])

from devscope_bridge.fs_routes import router as fs_router
app.include_router(fs_router, dependencies=[Depends(require_auth)])

from devscope_bridge.recording_routes import router as recording_router
app.include_router(recording_router, dependencies=[Depends(require_auth)])


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, version="0.1", uptime_s=int(time.time() - _start_time))


def _assert_loopback_host(host: str) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError(f"Dev Bridge must bind to loopback only. Refusing host={host!r}.")


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_LOG_MAX_BYTES = 50 * 1024 * 1024   # 50MB per file
_LOG_BACKUP_COUNT = 5               # ...x5 rotated files


def _configure_logging(log_dir: Path = BRIDGE_DIR) -> None:
    """A10/RC-12: timestamped, size-capped logs instead of an unbounded,
    timestamp-less stream. Bridge log files had grown to 312MB+3.2GB with no
    way to tell WHEN anything happened; uvicorn's access log also logged a
    line for every poll (GET /sessions, /transcript — hit every few seconds
    by a connected panel), drowning out anything worth reading.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_dir / "bridge.log", maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUP_COUNT,
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # Poll-heavy endpoints would otherwise log an access line every few
    # seconds per connected panel — demote to WARNING (errors still surface).
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def run() -> None:
    """Console entry point: ``devscope-bridge``.

    Always a single uvicorn process. Multi-worker uvicorn would break in-memory
    PTY terminals, WebSocket session pumps, and the orchestrator loop.
    Concurrent HTTP is handled by asyncio; transcript reads are semaphore-capped.
    Orchestrator Claude workers are capped via ORCHESTRATOR_MAX_WORKERS / config.
    """
    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_PORT", "7878"))
    _assert_loopback_host(host)
    _configure_logging()
    uvicorn.run(
        "devscope_bridge.main:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
        workers=1,
        # A10: uvicorn's own dictConfig would otherwise reset uvicorn.access
        # back to INFO with its own non-propagating handler, undoing the
        # _configure_logging() level/format above. log_config=None leaves our
        # root handlers as the only ones — uvicorn's loggers propagate to them.
        log_config=None,
        # log_level above re-applies INFO to uvicorn.access even with
        # log_config=None, so the polling noise (GET /sessions ~1Hz) must be
        # cut at the source; uvicorn.error still reports real problems.
        access_log=False,
    )


if __name__ == "__main__":
    run()

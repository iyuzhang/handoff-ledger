import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .generation import GenerationError, generate_handoff
from .routes import build_router
from .settings import Settings
from .store import Conflict, InvalidRequest, NotFound, Store


STATIC_DIR = Path(__file__).with_name("static")
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_REQUEST_BYTES = 2_500_000
LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Creates a single-worker local workspace application."""
    config = settings or Settings.from_env()
    store = Store(config.database_path)
    wake_worker = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.recover_interrupted_jobs()
        async with httpx.AsyncClient(timeout=config.timeout, follow_redirects=False) as client:
            worker = (
                asyncio.create_task(_run_jobs(store, config, client, wake_worker))
                if config.model_configured
                else None
            )
            try:
                yield
            finally:
                if worker is not None:
                    worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await worker

    app = FastAPI(
        title="Handoff Ledger",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    _install_boundary(app, config)
    app.include_router(build_router(store, config, wake_worker.set))
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def _install_boundary(app: FastAPI, settings: Settings) -> None:
    allowed_hosts = {host.strip("[]").lower() for host in settings.allowed_hosts}

    @app.middleware("http")
    async def boundary(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rejection = _check_request(request, allowed_hosts)
        response = rejection if rejection is not None else await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> Response:
        first = error.errors()[0]
        where = ".".join(str(item) for item in first["loc"] if item != "body")
        prefix = f"{where}: " if where else ""
        return _error(422, prefix + first["msg"])

    @app.exception_handler(NotFound)
    async def missing_record(_: Request, error: NotFound) -> Response:
        return _error(404, str(error))

    @app.exception_handler(Conflict)
    async def conflicted_record(_: Request, error: Conflict) -> Response:
        return _error(409, str(error))

    @app.exception_handler(InvalidRequest)
    async def invalid_record(_: Request, error: InvalidRequest) -> Response:
        return _error(422, str(error))

    @app.exception_handler(sqlite3.OperationalError)
    async def database_unavailable(_: Request, error: sqlite3.OperationalError) -> Response:
        LOGGER.error("SQLite operation failed: %s", error)
        return _error(503, "The workspace database is unavailable. Check the data directory and try again.")


def _check_request(request: Request, allowed_hosts: set[str]) -> Response | None:
    host = request.headers.get("host", "")
    try:
        authority = urlsplit(f"http://{host}")
        hostname = authority.hostname
    except ValueError:
        return _error(400, "Unrecognized Host header.")
    if hostname not in allowed_hosts or authority.username or authority.netloc != host:
        return _error(400, "Unrecognized Host header.")
    if request.method in SAFE_METHODS:
        return None

    origin = request.headers.get("origin")
    expected_origin = f"{request.url.scheme}://{host}"
    if (origin and origin.lower() != expected_origin.lower()) or request.headers.get("sec-fetch-site") in {
        "cross-site",
        "same-site",
    }:
        return _error(403, "Cross-origin workspace requests are blocked.")

    if request.method in {"POST", "PUT", "PATCH"}:
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type != "application/json":
            return _error(415, "Send an application/json request body.")
        size = request.headers.get("content-length", "")
        if not size.isdecimal():
            return _error(411, "Send a Content-Length header for JSON requests.")
        if len(size) > 10 or int(size) > MAX_REQUEST_BYTES:
            return _error(413, "The request exceeds the workspace size limit.")
    return None


def _error(status: int, detail: str) -> Response:
    return JSONResponse({"detail": detail}, status_code=status)


async def _run_jobs(
    store: Store, settings: Settings, client: httpx.AsyncClient, wake_worker: asyncio.Event
) -> None:
    needs_recovery = False
    while True:
        wake_worker.clear()
        try:
            if needs_recovery:
                await asyncio.to_thread(store.recover_interrupted_jobs)
                needs_recovery = False
            worked = await _run_next_job(store, settings, client)
        except sqlite3.Error:
            needs_recovery = True
            LOGGER.exception("The generation queue could not access the database")
            await asyncio.sleep(2)
        else:
            if not worked:
                with suppress(TimeoutError):
                    await asyncio.wait_for(wake_worker.wait(), timeout=30)


async def _run_next_job(store: Store, settings: Settings, client: httpx.AsyncClient) -> bool:
    claimed = await asyncio.to_thread(store.claim_job)
    if claimed is None:
        return False
    try:
        draft = await generate_handoff(settings, client, claimed.title, claimed.goal, claimed.sources)
        await asyncio.to_thread(store.complete_job, claimed.job.id, draft.summary, draft.steps, draft.gaps)
    except GenerationError as error:
        await asyncio.to_thread(store.fail_job, claimed.job.id, str(error))
    except asyncio.CancelledError:
        raise
    except (Conflict, NotFound, InvalidRequest, sqlite3.Error):
        LOGGER.exception("Failed to save generated handoff %s", claimed.job.id)
        await asyncio.to_thread(
            store.fail_job, claimed.job.id, "The draft could not be saved. Check the workspace and try again."
        )
    return True

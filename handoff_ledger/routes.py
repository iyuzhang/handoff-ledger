import asyncio
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from .exports import render_markdown
from .models import (
    FollowUpInput,
    Handoff,
    HandoffInput,
    HandoffSummary,
    HandoffUpdate,
    Job,
    JobInput,
    Project,
    ProjectInput,
    SealInput,
    Source,
    SourceContent,
    SourceInput,
    SourceUpdate,
)
from .settings import Settings
from .store import Store


def build_router(store: Store, settings: Settings, wake_worker: Callable[[], None]) -> APIRouter:
    """Binds workspace, evidence, review, and export endpoints."""
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict[str, str]:
        store.ping()
        return {"status": "ok"}

    @router.get("/config")
    def config() -> dict[str, str | bool | None]:
        return {"model_configured": settings.model_configured, "model": settings.model or None}

    @router.get("/projects")
    def list_projects() -> list[Project]:
        return store.list_projects()

    @router.post("/projects", status_code=201)
    def create_project(data: ProjectInput) -> Project:
        return store.create_project(data)

    @router.get("/projects/{pid}")
    def get_project(pid: str) -> Project:
        return store.get_project(pid)

    @router.patch("/projects/{pid}")
    def update_project(pid: str, data: ProjectInput) -> Project:
        return store.update_project(pid, data)

    @router.get("/projects/{pid}/sources")
    def list_sources(pid: str) -> list[Source]:
        return store.list_sources(pid)

    @router.post("/projects/{pid}/sources", status_code=201)
    def create_source(pid: str, data: SourceInput) -> SourceContent:
        return store.create_source(pid, data)

    @router.get("/projects/{pid}/sources/{sid}")
    def get_source(pid: str, sid: str, revision: int | None = Query(None, ge=1)) -> SourceContent:
        return store.get_source(pid, sid, revision)

    @router.put("/projects/{pid}/sources/{sid}")
    def update_source(pid: str, sid: str, data: SourceUpdate) -> SourceContent:
        return store.update_source(pid, sid, data)

    @router.get("/projects/{pid}/sources/{sid}/revisions")
    def list_source_revisions(pid: str, sid: str) -> list[Source]:
        return store.list_source_revisions(pid, sid)

    @router.delete("/projects/{pid}/sources/{sid}", status_code=204)
    def archive_source(pid: str, sid: str) -> None:
        store.archive_source(pid, sid)

    @router.get("/projects/{pid}/handoffs")
    def list_handoffs(pid: str) -> list[HandoffSummary]:
        return store.list_handoffs(pid)

    @router.post("/projects/{pid}/handoffs", status_code=201)
    def create_handoff(pid: str, data: HandoffInput) -> Handoff:
        return store.create_handoff(pid, data)

    @router.get("/projects/{pid}/handoffs/{hid}")
    def get_handoff(pid: str, hid: str) -> Handoff:
        return store.get_handoff(pid, hid)

    @router.put("/projects/{pid}/handoffs/{hid}")
    def update_handoff(pid: str, hid: str, data: HandoffUpdate) -> Handoff:
        return store.update_handoff(pid, hid, data)

    @router.delete("/projects/{pid}/handoffs/{hid}", status_code=204)
    def delete_handoff(pid: str, hid: str) -> None:
        store.delete_handoff(pid, hid)

    @router.post("/projects/{pid}/handoffs/{hid}/seal")
    def seal_handoff(pid: str, hid: str, data: SealInput) -> Handoff:
        return store.seal_handoff(pid, hid, data)

    @router.post("/projects/{pid}/handoffs/{hid}/follow-up", status_code=201)
    def follow_up(pid: str, hid: str, data: FollowUpInput) -> Handoff:
        return store.follow_up_handoff(pid, hid)

    @router.get("/projects/{pid}/handoffs/{hid}/export")
    def export_handoff(pid: str, hid: str, format: Literal["markdown", "json"] = "markdown") -> Response:
        handoff = store.get_handoff(pid, hid, live_evidence=False)
        if format == "json":
            body = handoff.model_dump_json(indent=2) + "\n"
            media_type = "application/json"
            extension = "json"
        else:
            body = render_markdown(handoff)
            media_type = "text/markdown"
            extension = "md"
        return Response(
            body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="handoff-{handoff.id}.{extension}"'},
        )

    @router.get("/projects/{pid}/jobs")
    def list_jobs(pid: str) -> list[Job]:
        return store.list_jobs(pid)

    @router.post("/projects/{pid}/jobs", status_code=202)
    async def create_job(pid: str, data: JobInput) -> Job:
        if not settings.model_configured:
            raise HTTPException(503, "Set LLM_BASE_URL and LLM_MODEL on the server to enable generation.")
        job = await asyncio.to_thread(store.create_job, pid, data)
        wake_worker()
        return job

    @router.get("/projects/{pid}/jobs/{jid}")
    def get_job(pid: str, jid: str) -> Job:
        return store.get_job(pid, jid)

    return router

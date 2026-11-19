import logging
import sqlite3
from dataclasses import dataclass
from typing import Literal

from handoff_ledger.models import Job, JobInput, SourceContent, Step, source_lines
from handoff_ledger.store_db import Conflict, InvalidRequest, NotFound, record_id, timestamp
from handoff_ledger.store_handoffs import HandoffStore, insert_handoff
from handoff_ledger.store_sources import SourceStore, get_source_revision, require_project


__all__ = ["ClaimedJob", "Conflict", "InvalidRequest", "NotFound", "Store"]

LOGGER = logging.getLogger(__name__)
MAX_JOB_SOURCE_CHARACTERS = 80_000


@dataclass(frozen=True)
class ClaimedJob:
    """Carries a job and the exact document versions selected at submission."""

    job: Job
    title: str
    goal: str
    sources: list[SourceContent]


class Store(HandoffStore, SourceStore):
    """Persists the workspace and coordinates generation job transactions."""

    def list_jobs(self, project_id: str) -> list[Job]:
        with self.transaction() as connection:
            require_project(connection, project_id)
            rows = connection.execute(
                "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC, id",
                (project_id,),
            ).fetchall()
            return [Job.model_validate(dict(row)) for row in rows]

    def get_job(self, project_id: str, job_id: str) -> Job:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE project_id = ? AND id = ?",
                (project_id, job_id),
            ).fetchone()
            if row is None:
                raise NotFound("Generation job was not found in this project.")
            return Job.model_validate(dict(row))

    def create_job(self, project_id: str, data: JobInput) -> Job:
        job_id = record_id()
        created_at = timestamp()
        with self.transaction(write=True) as connection:
            require_project(connection, project_id)
            _require_idle_project(connection, project_id)
            sources = [
                get_source_revision(connection, project_id, source_id, active_only=True)
                for source_id in data.source_ids
            ]
            if sum(len(source.content) for source in sources) > MAX_JOB_SOURCE_CHARACTERS:
                raise InvalidRequest("Selected documents exceed 80,000 characters. Select fewer or shorter sources.")

            connection.execute(
                """
                INSERT INTO jobs (id, project_id, title, goal, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?)
                """,
                (job_id, project_id, data.title, data.goal, created_at, created_at),
            )
            connection.executemany(
                """
                INSERT INTO job_sources (job_id, position, source_id, source_revision) VALUES (?, ?, ?, ?)
                """,
                (
                    (job_id, position, source.id, source.revision)
                    for position, source in enumerate(sources)
                ),
            )
            return Job.model_validate(dict(_require_job(connection, job_id)))

    def claim_job(self, job_id: str | None = None) -> ClaimedJob | None:
        """Claims one queued job and loads its immutable document revisions."""
        with self.transaction(write=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE state = 'queued' AND (? IS NULL OR id = ?)
                ORDER BY created_at, id
                LIMIT 1
                """,
                (job_id, job_id),
            ).fetchone()
            if row is None:
                return None
            job = _transition_job(connection, row["id"], "running")
            return ClaimedJob(
                job=job,
                title=row["title"],
                goal=row["goal"],
                sources=_load_job_sources(connection, row["project_id"], row["id"]),
            )

    def complete_job(self, job_id: str, summary: str, steps: list[Step], gaps: list[str]) -> Job:
        """Creates a draft and marks its generation job successful atomically."""
        with self.transaction(write=True) as connection:
            row = _require_job(connection, job_id)
            _require_running(row)
            sources = _load_job_sources(connection, row["project_id"], job_id)
            _check_evidence(sources, steps)
            handoff = insert_handoff(
                connection,
                row["project_id"],
                row["title"],
                row["goal"],
                summary,
                steps,
                gaps,
            )
            job = _transition_job(connection, job_id, "succeeded", handoff_id=handoff.id)
        LOGGER.info("Completed generation job %s", job_id)
        return job

    def fail_job(self, job_id: str, error: str) -> Job:
        """Records a failed generation and releases its project slot."""
        with self.transaction(write=True) as connection:
            row = _require_job(connection, job_id)
            _require_running(row)
            job = _transition_job(connection, job_id, "failed", error=error)
        LOGGER.warning("Generation job failed: %s", job_id)
        return job

    def recover_interrupted_jobs(self) -> int:
        """Marks interrupted work failed and keeps queued submissions available."""
        with self.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET state = 'failed', updated_at = ?, error = ?
                WHERE state = 'running'
                """,
                (timestamp(), "Generation was interrupted. Submit a new generation request to try again."),
            )
            recovered = cursor.rowcount
        if recovered:
            LOGGER.info("Recovered %d interrupted generation jobs", recovered)
        return recovered


def _require_idle_project(connection: sqlite3.Connection, project_id: str) -> None:
    row = connection.execute(
        "SELECT id FROM jobs WHERE project_id = ? AND state IN ('queued', 'running')",
        (project_id,),
    ).fetchone()
    if row is not None:
        raise Conflict("A generation job is already active for this project.")


def _require_job(connection: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise NotFound("Generation job was not found.")
    return row


def _require_running(job: sqlite3.Row) -> None:
    if job["state"] != "running":
        raise Conflict("This generation job has already stopped running.")


def _load_job_sources(connection: sqlite3.Connection, project_id: str, job_id: str) -> list[SourceContent]:
    rows = connection.execute(
        """
        SELECT source_id, source_revision FROM job_sources
        WHERE job_id = ?
        ORDER BY position
        """,
        (job_id,),
    ).fetchall()
    return [
        get_source_revision(connection, project_id, row["source_id"], row["source_revision"])
        for row in rows
    ]


def _check_evidence(sources: list[SourceContent], steps: list[Step]) -> None:
    line_index = {source.id: (source, source_lines(source.content)) for source in sources}
    for step in steps:
        for evidence in step.evidence:
            record = line_index.get(evidence.source_id)
            if record is None:
                raise InvalidRequest("Generated evidence references a document outside this generation request.")
            source, lines = record
            if (
                evidence.source_name != source.name
                or evidence.revision != source.revision
                or not 1 <= evidence.start_line <= evidence.end_line <= len(lines)
            ):
                raise InvalidRequest("Generated evidence does not match its pinned document revision.")
            quoted_lines = lines[evidence.start_line - 1 : evidence.end_line]
            if len(quoted_lines) == 1:
                matches = bool(evidence.excerpt) and evidence.excerpt in quoted_lines[0]
            else:
                matches = evidence.excerpt == "\n".join(quoted_lines)
            if not matches:
                raise InvalidRequest("Generated evidence does not match its pinned document revision.")


def _transition_job(
    connection: sqlite3.Connection,
    job_id: str,
    state: Literal["running", "succeeded", "failed"],
    *,
    handoff_id: str | None = None,
    error: str | None = None,
) -> Job:
    row = connection.execute(
        """
        UPDATE jobs SET state = ?, updated_at = ?, handoff_id = ?, error = ? WHERE id = ?
        RETURNING *
        """,
        (state, timestamp(), handoff_id, error, job_id),
    ).fetchone()
    return Job.model_validate(dict(row))

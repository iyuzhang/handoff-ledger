import sqlite3

from handoff_ledger.models import Project, ProjectInput, Source, SourceContent, SourceInput, SourceUpdate, source_lines
from handoff_ledger.store_db import Conflict, Database, NotFound, record_id, timestamp


MAX_SQLITE_INTEGER = (1 << 63) - 1


class SourceStore(Database):
    """Persists projects and append-only document revisions."""

    def list_projects(self) -> list[Project]:
        with self.transaction() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY created_at DESC, id").fetchall()
            return [Project.model_validate(dict(row)) for row in rows]

    def get_project(self, project_id: str) -> Project:
        with self.transaction() as connection:
            return _get_project(connection, project_id)

    def create_project(self, data: ProjectInput) -> Project:
        project = Project(id=record_id(), name=data.name, description=data.description, created_at=timestamp())
        with self.transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO projects (id, name, description, created_at) VALUES (?, ?, ?, ?)",
                (project.id, project.name, project.description, project.created_at),
            )
        return project

    def update_project(self, project_id: str, data: ProjectInput) -> Project:
        with self.transaction(write=True) as connection:
            connection.execute(
                "UPDATE projects SET name = ?, description = ? WHERE id = ?",
                (data.name, data.description, project_id),
            )
            return _get_project(connection, project_id)

    def list_sources(self, project_id: str) -> list[Source]:
        with self.transaction() as connection:
            require_project(connection, project_id)
            rows = connection.execute(
                """
                SELECT s.id, s.project_id, s.name, r.revision, s.created_at,
                       r.created_at AS updated_at, r.line_count
                FROM sources AS s
                JOIN source_revisions AS r ON r.source_id = s.id AND r.revision = s.current_revision
                WHERE s.project_id = ? AND s.archived_at IS NULL
                ORDER BY s.created_at DESC, s.id
                """,
                (project_id,),
            ).fetchall()
            return [Source.model_validate(dict(row)) for row in rows]

    def create_source(self, project_id: str, data: SourceInput) -> SourceContent:
        source_id = record_id()
        created_at = timestamp()
        with self.transaction(write=True) as connection:
            require_project(connection, project_id)
            connection.execute(
                """
                INSERT INTO sources (id, project_id, name, current_revision, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (source_id, project_id, data.name, created_at),
            )
            _insert_revision(connection, source_id, 1, data.content, created_at)
            return get_source_revision(connection, project_id, source_id)

    def get_source(self, project_id: str, source_id: str, revision: int | None = None) -> SourceContent:
        with self.transaction() as connection:
            return get_source_revision(connection, project_id, source_id, revision)

    def update_source(self, project_id: str, source_id: str, data: SourceUpdate) -> SourceContent:
        with self.transaction(write=True) as connection:
            current = get_source_revision(connection, project_id, source_id, active_only=True)
            if current.revision != data.expected_revision:
                raise Conflict("Source changed since it was opened. Reload the source and try again.")
            if current.content == data.content:
                return current

            revision = current.revision + 1
            _insert_revision(connection, source_id, revision, data.content, timestamp())
            connection.execute("UPDATE sources SET current_revision = ? WHERE id = ?", (revision, source_id))
            return get_source_revision(connection, project_id, source_id, revision)

    def list_source_revisions(self, project_id: str, source_id: str) -> list[Source]:
        with self.transaction() as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.project_id, s.name, r.revision, s.created_at,
                       r.created_at AS updated_at, r.line_count
                FROM sources AS s
                JOIN source_revisions AS r ON r.source_id = s.id
                WHERE s.project_id = ? AND s.id = ?
                ORDER BY r.revision DESC
                """,
                (project_id, source_id),
            ).fetchall()
            if not rows:
                raise NotFound("Source was not found in this project.")
            return [Source.model_validate(dict(row)) for row in rows]

    def archive_source(self, project_id: str, source_id: str) -> None:
        with self.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE sources SET archived_at = COALESCE(archived_at, ?)
                WHERE project_id = ? AND id = ?
                """,
                (timestamp(), project_id, source_id),
            )
            if cursor.rowcount == 0:
                raise NotFound("Source was not found in this project.")


def require_project(connection: sqlite3.Connection, project_id: str) -> None:
    """Checks that the project exists before a scoped operation."""
    if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise NotFound("Project was not found.")


def get_source_revision(
    connection: sqlite3.Connection,
    project_id: str,
    source_id: str,
    revision: int | None = None,
    *,
    active_only: bool = False,
) -> SourceContent:
    """Loads one immutable document version, optionally requiring an active source."""
    if revision is not None and not 1 <= revision <= MAX_SQLITE_INTEGER:
        raise NotFound("Source or requested revision was not found in this project.")
    row = connection.execute(
        """
        SELECT s.id, s.project_id, s.name, s.archived_at, r.revision,
               s.created_at, r.created_at AS updated_at, r.line_count, r.content
        FROM sources AS s
        JOIN source_revisions AS r ON r.source_id = s.id AND r.revision = COALESCE(?, s.current_revision)
        WHERE s.project_id = ? AND s.id = ?
        """,
        (revision, project_id, source_id),
    ).fetchone()
    if row is None:
        raise NotFound("Source or requested revision was not found in this project.")
    if active_only and row["archived_at"] is not None:
        raise Conflict("This source was archived. Select an active source.")
    source_data = dict(row)
    del source_data["archived_at"]
    return SourceContent.model_validate(source_data)


def _get_project(connection: sqlite3.Connection, project_id: str) -> Project:
    row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise NotFound("Project was not found.")
    return Project.model_validate(dict(row))


def _insert_revision(
    connection: sqlite3.Connection,
    source_id: str,
    revision: int,
    content: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO source_revisions (source_id, revision, content, line_count, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_id, revision, content, len(source_lines(content)), created_at),
    )

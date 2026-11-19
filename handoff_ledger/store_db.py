from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from uuid import uuid4


SCHEMA_VERSION = 2
SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sources (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        name TEXT NOT NULL,
        current_revision INTEGER NOT NULL CHECK (current_revision > 0),
        created_at TEXT NOT NULL,
        archived_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS sources_project ON sources(project_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS source_revisions (
        source_id TEXT NOT NULL REFERENCES sources(id),
        revision INTEGER NOT NULL CHECK (revision > 0),
        content TEXT NOT NULL,
        line_count INTEGER NOT NULL CHECK (line_count > 0),
        created_at TEXT NOT NULL,
        PRIMARY KEY (source_id, revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS handoffs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        title TEXT NOT NULL,
        goal TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('draft', 'sealed')),
        revision INTEGER NOT NULL CHECK (revision > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        summary TEXT NOT NULL,
        steps TEXT NOT NULL,
        gaps TEXT NOT NULL,
        review_notes TEXT NOT NULL,
        reviewer TEXT,
        sealed_at TEXT,
        outcome TEXT CHECK (outcome IN ('ready', 'blocked'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS handoffs_project ON handoffs(project_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        title TEXT NOT NULL,
        goal TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed')),
        handoff_id TEXT REFERENCES handoffs(id) ON DELETE SET NULL,
        error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(created_at) WHERE state = 'queued'
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_per_project ON jobs(project_id)
        WHERE state IN ('queued', 'running')
    """,
    """
    CREATE TABLE IF NOT EXISTS job_sources (
        job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        source_id TEXT NOT NULL,
        source_revision INTEGER NOT NULL,
        PRIMARY KEY (job_id, position),
        UNIQUE (job_id, source_id),
        FOREIGN KEY (source_id, source_revision) REFERENCES source_revisions(source_id, revision)
    )
    """,
)


class NotFound(LookupError):
    """Indicates a missing record within its requested scope."""


class Conflict(ValueError):
    """Indicates that a requested write conflicts with persisted state."""


class InvalidRequest(ValueError):
    """Indicates that a request violates a domain rule."""


class Database:
    """Opens a short-lived SQLite connection per transaction."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def ping(self) -> None:
        """Checks that the database schema can be read."""
        with self.transaction() as connection:
            connection.execute("SELECT id FROM projects LIMIT 1").fetchone()

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Commits one operation in a consistent read or write transaction."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    for statement in SCHEMA:
                        connection.execute(statement)
                    version = 1
                if version == 1:
                    connection.execute("ALTER TABLE handoffs ADD COLUMN parent_handoff_id TEXT REFERENCES handoffs(id)")
                    connection.execute("PRAGMA user_version = 2")
                elif version != SCHEMA_VERSION:
                    raise RuntimeError(f"Unsupported database schema version {version}.")



def timestamp() -> str:
    """Returns the current time as an ISO 8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


def record_id() -> str:
    """Creates a UUID for a persisted record."""
    return str(uuid4())

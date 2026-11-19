import sqlite3

from pydantic import TypeAdapter

from handoff_ledger.models import (
    Evidence,
    EvidenceSelection,
    Handoff,
    HandoffInput,
    HandoffSummary,
    HandoffUpdate,
    SealInput,
    SourceContent,
    Step,
    source_lines,
)
from handoff_ledger.store_db import Conflict, Database, InvalidRequest, NotFound, record_id, timestamp
from handoff_ledger.store_sources import get_source_revision, require_project


STEPS_ADAPTER = TypeAdapter(list[Step])
GAPS_ADAPTER = TypeAdapter(list[str])
MAX_MANUAL_EVIDENCE_CHARACTERS = 3000


class HandoffStore(Database):
    """Persists handoff drafts, reviews, and sealed snapshots."""

    def list_handoffs(self, project_id: str) -> list[HandoffSummary]:
        with self.transaction() as connection:
            require_project(connection, project_id)
            rows = connection.execute(
                """
                SELECT id, project_id, title, goal, state, revision, created_at, updated_at,
                       reviewer, sealed_at, outcome, parent_handoff_id
                FROM handoffs
                WHERE project_id = ?
                ORDER BY updated_at DESC, id
                """,
                (project_id,),
            ).fetchall()
            return [HandoffSummary.model_validate(dict(row)) for row in rows]

    def create_handoff(self, project_id: str, data: HandoffInput) -> Handoff:
        with self.transaction(write=True) as connection:
            require_project(connection, project_id)
            return insert_handoff(connection, project_id, data.title, data.goal, "", [], [])

    def get_handoff(self, project_id: str, handoff_id: str, *, live_evidence: bool = True) -> Handoff:
        with self.transaction() as connection:
            return _get_handoff(connection, project_id, handoff_id, live_evidence=live_evidence)

    def update_handoff(self, project_id: str, handoff_id: str, data: HandoffUpdate) -> Handoff:
        with self.transaction(write=True) as connection:
            current = _get_handoff(connection, project_id, handoff_id)
            _require_editable(current, data.expected_revision)
            steps = _merge_steps(connection, current, data)
            connection.execute(
                """
                UPDATE handoffs
                SET title = ?, goal = ?, summary = ?, steps = ?, gaps = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    data.title,
                    data.goal,
                    data.summary,
                    STEPS_ADAPTER.dump_json(steps).decode(),
                    GAPS_ADAPTER.dump_json(data.gaps).decode(),
                    timestamp(),
                    handoff_id,
                ),
            )
            return _get_handoff(connection, project_id, handoff_id)

    def delete_handoff(self, project_id: str, handoff_id: str) -> None:
        with self.transaction(write=True) as connection:
            current = _get_handoff(connection, project_id, handoff_id)
            _require_editable(current)
            connection.execute("DELETE FROM handoffs WHERE id = ?", (handoff_id,))

    def follow_up_handoff(self, project_id: str, handoff_id: str) -> Handoff:
        """Creates a new draft for reviewing an existing sealed handoff."""
        with self.transaction(write=True) as connection:
            parent = _get_handoff(connection, project_id, handoff_id, live_evidence=False)
            if parent.state != "sealed":
                raise Conflict("Seal this handoff before starting a follow-up review.")
            steps = [
                step.model_copy(update={"id": record_id(), "status": "pending", "notes": ""})
                for step in parent.steps
            ]
            return insert_handoff(
                connection,
                project_id,
                parent.title,
                parent.goal,
                parent.summary,
                steps,
                parent.gaps,
                parent_handoff_id=parent.id,
            )

    def seal_handoff(self, project_id: str, handoff_id: str, data: SealInput) -> Handoff:
        with self.transaction(write=True) as connection:
            current = _get_handoff(connection, project_id, handoff_id)
            _require_editable(current, data.expected_revision)
            _require_complete_review(current, data)
            outcome = "blocked" if any(step.status == "blocked" for step in current.steps) else "ready"
            sealed_at = timestamp()
            connection.execute(
                """
                UPDATE handoffs
                SET state = 'sealed', reviewer = ?, sealed_at = ?, review_notes = ?,
                    outcome = ?, steps = ?, revision = revision + 1, updated_at = ?
                WHERE id = ?
                """,
                (
                    data.reviewer,
                    sealed_at,
                    data.review_notes,
                    outcome,
                    STEPS_ADAPTER.dump_json(current.steps).decode(),
                    sealed_at,
                    handoff_id,
                ),
            )
            return _get_handoff(connection, project_id, handoff_id, live_evidence=False)


def insert_handoff(
    connection: sqlite3.Connection,
    project_id: str,
    title: str,
    goal: str,
    summary: str,
    steps: list[Step],
    gaps: list[str],
    *,
    parent_handoff_id: str | None = None,
) -> Handoff:
    """Creates a draft inside the caller's write transaction."""
    handoff_id = record_id()
    created_at = timestamp()
    connection.execute(
        """
        INSERT INTO handoffs (id, project_id, parent_handoff_id, title, goal, summary, steps, gaps, review_notes,
                              state, revision, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', 'draft', 1, ?, ?)
        """,
        (
            handoff_id,
            project_id,
            parent_handoff_id,
            title,
            goal,
            summary,
            STEPS_ADAPTER.dump_json(steps).decode(),
            GAPS_ADAPTER.dump_json(gaps).decode(),
            created_at,
            created_at,
        ),
    )
    return _get_handoff(connection, project_id, handoff_id)


def _get_handoff(
    connection: sqlite3.Connection,
    project_id: str,
    handoff_id: str,
    *,
    live_evidence: bool = True,
) -> Handoff:
    row = connection.execute(
        "SELECT * FROM handoffs WHERE project_id = ? AND id = ?",
        (project_id, handoff_id),
    ).fetchone()
    if row is None:
        raise NotFound("Handoff was not found in this project.")
    steps = STEPS_ADAPTER.validate_json(row["steps"])
    if live_evidence or row["state"] == "draft":
        steps = _refresh_evidence(connection, project_id, steps)
    return Handoff.model_validate(dict(row) | {"steps": steps, "gaps": GAPS_ADAPTER.validate_json(row["gaps"])})


def _refresh_evidence(connection: sqlite3.Connection, project_id: str, steps: list[Step]) -> list[Step]:
    if not any(step.evidence for step in steps):
        return steps
    rows = connection.execute(
        "SELECT id, current_revision FROM sources WHERE project_id = ? AND archived_at IS NULL",
        (project_id,),
    )
    active_revisions = {row["id"]: row["current_revision"] for row in rows}
    return [
        step.model_copy(
            update={
                "evidence": [
                    evidence.model_copy(update={"stale": active_revisions.get(evidence.source_id) != evidence.revision})
                    for evidence in step.evidence
                ],
            }
        )
        for step in steps
    ]


def _require_editable(current: Handoff, expected_revision: int | None = None) -> None:
    if current.state == "sealed":
        raise Conflict("This handoff is sealed. Create a new draft to continue reviewing.")
    if expected_revision is not None and current.revision != expected_revision:
        raise Conflict("Handoff changed since it was opened. Reload it and try again.")


def _merge_steps(connection: sqlite3.Connection, current: Handoff, data: HandoffUpdate) -> list[Step]:
    existing_steps = {step.id: step for step in current.steps}
    merged: list[Step] = []
    used_ids: set[str] = set()
    source_cache: dict[tuple[str, int], tuple[SourceContent, list[str]]] = {}
    for edit in data.steps:
        previous = existing_steps.get(edit.id) if edit.id is not None else None
        if edit.id is not None and previous is None:
            raise InvalidRequest("A step does not belong to this handoff. Reload the draft and try again.")
        step_id = previous.id if previous is not None else record_id()
        if step_id in used_ids:
            raise InvalidRequest("Each existing step can appear only once in the draft.")
        evidence = previous.evidence if previous is not None else []
        if edit.evidence is not None:
            evidence = _pin_evidence(connection, current.project_id, edit.evidence, source_cache, evidence)
        step = Step(
            id=step_id,
            title=edit.title,
            instruction=edit.instruction,
            verify=edit.verify,
            evidence=evidence,
            status=edit.status,
            notes=edit.notes,
        )
        if previous is not None and previous.status != "pending" and _review_content_changed(previous, step):
            step = step.model_copy(update={"status": "pending"})
        merged.append(step)
        used_ids.add(step_id)
    return merged


def _pin_evidence(
    connection: sqlite3.Connection,
    project_id: str,
    selections: list[EvidenceSelection],
    source_cache: dict[tuple[str, int], tuple[SourceContent, list[str]]],
    previous: list[Evidence],
) -> list[Evidence]:
    evidence: list[Evidence] = []
    reused: set[int] = set()
    for selection in selections:
        index = selection.existing_index
        if index is not None:
            if index in reused or index >= len(previous) or _coordinates(selection) != _coordinates(previous[index]):
                raise InvalidRequest("An existing citation no longer matches the draft. Reload and try again.")
            reused.add(index)
            evidence.append(previous[index])
            continue
        key = (selection.source_id, selection.revision)
        if key not in source_cache:
            source = get_source_revision(connection, project_id, selection.source_id, selection.revision)
            source_cache[key] = (source, source_lines(source.content))
        source, lines = source_cache[key]
        if not 1 <= selection.start_line <= selection.end_line <= len(lines):
            raise InvalidRequest(f"Choose an evidence line range from 1 to {len(lines)}.")
        excerpt = "\n".join(lines[selection.start_line - 1 : selection.end_line])
        if len(excerpt) > MAX_MANUAL_EVIDENCE_CHARACTERS:
            raise InvalidRequest("Evidence exceeds 3,000 characters. Select a shorter line range.")
        evidence.append(
            Evidence(
                source_id=source.id,
                source_name=source.name,
                revision=source.revision,
                start_line=selection.start_line,
                end_line=selection.end_line,
                excerpt=excerpt,
            )
        )
    return evidence


def _evidence_keys(evidence: list[Evidence]) -> list[tuple[str, int, int, int, str]]:
    return [(*_coordinates(item), item.excerpt) for item in evidence]


def _coordinates(item: Evidence | EvidenceSelection) -> tuple[str, int, int, int]:
    return item.source_id, item.revision, item.start_line, item.end_line


def _review_content_changed(previous: Step, updated: Step) -> bool:
    return (
        (updated.title, updated.instruction, updated.verify) != (previous.title, previous.instruction, previous.verify)
        or _evidence_keys(updated.evidence) != _evidence_keys(previous.evidence)
    )


def _require_complete_review(current: Handoff, data: SealInput) -> None:
    if not current.steps or any(step.status == "pending" for step in current.steps):
        raise Conflict("Add at least one step and review every step before sealing this handoff.")
    has_blockers = (
        bool(current.gaps)
        or any(step.status == "blocked" for step in current.steps)
        or any(evidence.stale for step in current.steps for evidence in step.evidence)
    )
    if has_blockers and not data.review_notes:
        raise Conflict("Explain how gaps, stale evidence, and blocked steps affect the handoff before sealing.")

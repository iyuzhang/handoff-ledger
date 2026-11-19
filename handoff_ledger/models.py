from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Goal = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Instruction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Gap = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
RecordId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
ReviewStatus = Literal["pending", "verified", "blocked"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectInput(InputModel):
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class Project(ProjectInput):
    id: str
    created_at: str


class SourceText(InputModel):
    content: str = Field(min_length=1, max_length=200_000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, content: str) -> str:
        if not content.strip() or "\x00" in content:
            raise ValueError("Provide a nonempty UTF-8 text document.")
        return content.replace("\r\n", "\n").replace("\r", "\n")


class SourceInput(SourceText):
    name: Name


class SourceUpdate(SourceText):
    expected_revision: int = Field(ge=1)


class Source(BaseModel):
    id: str
    project_id: str
    name: str
    revision: int
    created_at: str
    updated_at: str
    line_count: int


class SourceContent(Source):
    content: str


class Evidence(BaseModel):
    source_id: str
    source_name: str
    revision: int
    start_line: int
    end_line: int
    excerpt: str
    stale: bool = False


class EvidenceSelection(InputModel):
    source_id: RecordId
    revision: int = Field(ge=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    existing_index: int | None = Field(default=None, ge=0, lt=6)


class Step(BaseModel):
    id: str
    title: Name
    instruction: Instruction
    verify: Instruction
    evidence: list[Evidence] = Field(default_factory=list)
    status: ReviewStatus = "pending"
    notes: Notes = ""


class StepUpdate(InputModel):
    id: RecordId | None = None
    title: Name
    instruction: Instruction
    verify: Instruction
    status: ReviewStatus = "pending"
    notes: Notes = ""
    evidence: list[EvidenceSelection] | None = Field(default=None, max_length=6)


class HandoffInput(InputModel):
    title: Name
    goal: Goal


class HandoffUpdate(HandoffInput):
    expected_revision: int = Field(ge=1)
    summary: Summary = ""
    steps: list[StepUpdate] = Field(max_length=40)
    gaps: list[Gap] = Field(max_length=40)


class HandoffSummary(BaseModel):
    id: str
    project_id: str
    title: str
    goal: str
    state: Literal["draft", "sealed"]
    revision: int
    created_at: str
    updated_at: str
    reviewer: str | None = None
    sealed_at: str | None = None
    outcome: Literal["ready", "blocked"] | None = None
    parent_handoff_id: str | None = None


class Handoff(HandoffSummary):
    summary: str = ""
    steps: list[Step] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    review_notes: str = ""


class SealInput(InputModel):
    expected_revision: int = Field(ge=1)
    reviewer: Name
    review_notes: Notes = ""


class FollowUpInput(InputModel):
    """Validates a request to copy a sealed handoff."""


class JobInput(HandoffInput):
    source_ids: list[RecordId] = Field(min_length=1, max_length=16)

    @field_validator("source_ids")
    @classmethod
    def unique_source_ids(cls, source_ids: list[str]) -> list[str]:
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("Select each source once.")
        return source_ids


class Job(BaseModel):
    id: str
    project_id: str
    state: Literal["queued", "running", "succeeded", "failed"]
    handoff_id: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


def source_lines(content: str) -> list[str]:
    """Returns the displayed lines of a normalized source."""
    return content.removesuffix("\n").split("\n")

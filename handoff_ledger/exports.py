import re

from .models import Handoff, Step


def render_markdown(handoff: Handoff) -> str:
    """Renders a portable checklist and its revision-pinned evidence."""
    lines = [
        f"# {_markdown_text(handoff.title)}",
        "",
        f"- **Project ID** `{handoff.project_id}`",
        f"- **Handoff ID** `{handoff.id}`",
        f"- **Record revision** {handoff.revision}",
        f"- **State** {handoff.state}",
        f"- **Updated (UTC)** {handoff.updated_at}",
    ]
    if handoff.parent_handoff_id:
        lines.append(f"- **Previous handoff** `{handoff.parent_handoff_id}`")
    if handoff.state == "sealed":
        lines.extend(
            [
                f"- **Outcome** {handoff.outcome}",
                f"- **Reviewer** {_markdown_text(handoff.reviewer or '')}",
                f"- **Sealed (UTC)** {handoff.sealed_at}",
            ]
        )
    lines.extend(["", "## Goal", "", _markdown_text(handoff.goal)])
    if handoff.summary:
        lines.extend(["", "## Summary", "", _markdown_text(handoff.summary)])
    lines.extend(["", "## Checklist", ""])
    for index, step in enumerate(handoff.steps, 1):
        lines.extend(_render_step(index, step))
    if not handoff.steps:
        lines.extend(["No steps recorded.", ""])
    if handoff.gaps:
        lines.extend(["## Gaps", ""])
        for gap in handoff.gaps:
            lines.append(f"- {_markdown_text(gap).replace(chr(10), ' ')}")
        lines.append("")
    if handoff.review_notes:
        lines.extend(["## Review notes", "", _markdown_text(handoff.review_notes), ""])
    return "\n".join(lines).rstrip() + "\n"


def _render_step(index: int, step: Step) -> list[str]:
    lines = [
        f"### {index}. {_markdown_text(step.title)}",
        "",
        f"**Review** {step.status}",
        "",
        _markdown_text(step.instruction),
        "",
        f"**Verify** {_markdown_text(step.verify)}",
        "",
    ]
    if step.notes:
        lines.extend([f"**Review notes** {_markdown_text(step.notes)}", ""])
    for evidence in step.evidence:
        lines.extend(
            [
                f"**Source** {_markdown_text(evidence.source_name)} · revision {evidence.revision}"
                f" · lines {evidence.start_line}–{evidence.end_line}"
                f"{' · source changed' if evidence.stale else ''}",
                "",
                _fenced(evidence.excerpt),
                "",
            ]
        )
    return lines


def _markdown_text(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>#~|!&])", r"\\\1", value)


def _fenced(value: str) -> str:
    longest = max((len(match.group()) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{value}\n{fence}"

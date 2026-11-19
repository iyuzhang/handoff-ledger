import { badge, button, closeDialog, field, formDialog, node, notice, projectPath, request, showDialog } from "./ui.js";

const PAGE_SIZE = 200;
const MAX_SOURCE_LENGTH = 200000;

export function renderContext(container, sources, step, actions) {
  const library = node("section");
  const libraryHeading = node("div", "context-title");
  const addSource = button("＋", "icon-button", actions.add);
  addSource.setAttribute("aria-label", "Add a source");
  addSource.title = "Add a source";
  libraryHeading.append(node("h2", "", "Sources"), addSource);
  library.append(libraryHeading);
  if (!sources.length) {
    library.append(node("p", "empty-text", "Add reference documents so the handoff can point to their exact wording."));
  }
  for (const source of sources) {
    const item = button("", "source-link", () => actions.open(source));
    item.append(node("strong", "", source.name), node("small", "", `Revision ${source.revision} · ${source.line_count} lines`));
    library.append(item);
  }

  const evidence = node("section");
  const evidenceTitle = node("div", "context-title");
  const heading = node("h2", "", "Step evidence");
  heading.id = "evidence-heading";
  heading.tabIndex = -1;
  evidenceTitle.append(heading);
  if (step && actions.pin && sources.length) {
    const pin = button("Pin excerpt", "button compact", actions.pin);
    pin.disabled = step.evidence.length >= 6;
    if (pin.disabled) pin.title = "Each step can contain at most six excerpts";
    evidenceTitle.append(pin);
  }
  evidence.append(evidenceTitle);
  if (!step) {
    evidence.append(node("p", "empty-text", "Select a step to inspect the source it cites."));
  } else {
    evidence.append(node("p", "empty-text evidence-caption", step.title || "Untitled step"));
    if (!step.evidence.length) evidence.append(node("p", "empty-text", "This step has no linked source excerpts."));
    const excerpts = node("div", "evidence-list");
    for (const quote of step.evidence) {
      const active = sources.find((source) => source.id === quote.source_id);
      excerpts.append(evidenceCard(quote, active, actions.openExcerpt, actions.remove));
    }
    evidence.append(excerpts);
  }
  container.replaceChildren(evidence, library);
}

export function importSource(project, onSaved) {
  const name = field("Source name", "name", { max: 160, required: true, placeholder: "e.g. Support rotation.md" });
  const content = field("Source text", "content", { rows: 11, max: MAX_SOURCE_LENGTH, required: true });
  const fileLabel = node("label", "field");
  const upload = node("input");
  upload.type = "file";
  upload.accept = ".md,.markdown,.mdx,.txt,text/plain,text/markdown";
  fileLabel.append(node("span", "", "Choose a text file (optional)"), upload);
  const note = node("p", "field-note", "Use Markdown or plain text, up to 200,000 characters. Sources are sent to your configured model only when selected for generation.");
  const { error } = formDialog("Add a source", "Add source", [name.wrapper, fileLabel, content.wrapper, note], async (data) => {
    const source = await request(projectPath(project.id, "/sources"), "POST", {
      name: data.get("name"), content: data.get("content"),
    });
    closeDialog();
    notice(`Added “${source.name}”.`);
    await onSaved();
  });
  upload.addEventListener("change", async () => {
    error.hidden = true;
    const file = upload.files[0];
    if (!file) return;
    try {
      if (file.size > MAX_SOURCE_LENGTH * 4) throw new Error("Choose a file with at most 200,000 characters.");
      const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (file !== upload.files[0]) return;
      if (text.length > MAX_SOURCE_LENGTH) throw new Error("Choose a file with at most 200,000 characters.");
      if (text.includes("\0")) throw new Error("Choose a Markdown or plain-text file.");
      if (!name.control.value) name.control.value = file.name.slice(0, 160);
      content.control.value = text;
    } catch (exception) {
      if (file !== upload.files[0]) return;
      upload.value = "";
      error.textContent = exception instanceof TypeError ? "Choose a UTF-8 Markdown or plain-text file." : exception.message;
      error.hidden = false;
    }
  });
}

export async function openSource(project, sourceId, { active, quote, onSaved }) {
  const path = projectPath(project.id, `/sources/${encodeURIComponent(sourceId)}`);
  const initialPath = quote ? `${path}?revision=${quote.revision}` : path;
  const [source, revisions] = await Promise.all([request(initialPath), request(`${path}/revisions`)]);
  showSource(source, path, revisions, active, quote, onSaved);
}

function evidenceCard(quote, active, open, remove) {
  const card = node("article", "evidence-card");
  const lineLabel = quote.start_line === quote.end_line ? `Line ${quote.start_line}` : `Lines ${quote.start_line}–${quote.end_line}`;
  card.append(node("strong", "", quote.source_name), node("p", "field-note", `Revision ${quote.revision} · ${lineLabel}`));
  if (quote.stale || !active || active.revision !== quote.revision) card.append(badge("stale", "Source changed"));
  const controls = node("div", "record-actions");
  controls.append(button("Open citation ↗", "button compact", () => open(quote)));
  if (remove) {
    const erase = button("Remove", "button compact danger", () => remove(quote));
    erase.setAttribute("aria-label", `Remove citation to ${quote.source_name} lines ${quote.start_line} to ${quote.end_line}`);
    controls.append(erase);
  }
  card.append(node("pre", "", quote.excerpt), controls);
  return card;
}

function showSource(initial, path, revisions, active, quote, onSaved) {
  const container = node("div", "dialog-form");
  const toolbar = node("div", "source-controls");
  const label = node("label", "field", "Revision");
  const select = node("select");
  for (const revision of revisions) {
    const option = node("option", "", `Revision ${revision.revision}`);
    option.value = String(revision.revision);
    select.append(option);
  }
  label.append(select);
  const edit = button("Add revision", "button", () => editSource(source, path, onSaved));
  const archive = button("Archive source", "button danger", () => archiveSource(source, path, onSaved));
  toolbar.append(label, edit, archive);
  const metadata = node("p", "field-note");
  const error = node("p", "form-error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  const pager = node("div", "source-page");
  const prev = button("← Previous lines", "button compact", () => changePage(start - PAGE_SIZE));
  const page = node("span");
  const next = button("Next lines →", "button compact", () => changePage(start + PAGE_SIZE));
  pager.append(prev, page, next);
  const viewer = node("div", "source-viewer");
  viewer.tabIndex = 0;
  viewer.setAttribute("aria-label", "Source text");
  container.append(toolbar, metadata, error, pager, viewer);

  let source = initial;
  let lines = [];
  let start = 1;
  let highlight = null;
  let selection = 0;
  loadView(initial);
  select.addEventListener("change", async () => {
    const currentSelection = ++selection;
    select.disabled = true;
    edit.disabled = true;
    archive.disabled = true;
    error.hidden = true;
    try {
      const revision = await request(`${path}?revision=${encodeURIComponent(select.value)}`);
      if (currentSelection === selection) loadView(revision);
    } catch (exception) {
      if (currentSelection !== selection) return;
      select.value = String(source.revision);
      error.textContent = exception.message;
      error.hidden = false;
    } finally {
      if (currentSelection === selection) {
        select.disabled = false;
        syncActions();
      }
    }
  });
  showDialog(initial.name, container, "wide");

  function loadView(value) {
    source = value;
    lines = value.content.split(/\r\n|\r|\n/).slice(0, value.line_count);
    select.value = String(value.revision);
    highlight = quote?.revision === value.revision ? quote : null;
    metadata.textContent = `${value.line_count} lines${active ? "" : " · Archived source"}${highlight ? ` · Cited lines ${highlight.start_line}–${highlight.end_line}` : ""}`;
    changePage(highlight ? Math.floor((highlight.start_line - 1) / PAGE_SIZE) * PAGE_SIZE + 1 : 1);
    if (highlight) requestAnimationFrame(() => viewer.querySelector('[data-highlight="true"]')?.scrollIntoView({ block: "nearest" }));
    syncActions();
  }

  function syncActions() {
    const latest = Math.max(...revisions.map((item) => item.revision), initial.revision);
    edit.hidden = !active;
    edit.disabled = source.revision !== latest;
    edit.title = edit.disabled ? "Switch to the latest revision to add a revision" : "";
    archive.hidden = !active;
    archive.disabled = false;
  }

  function changePage(first) {
    start = first;
    const end = Math.min(first + PAGE_SIZE - 1, lines.length);
    const rows = [];
    for (let number = first; number <= end; number += 1) {
      const line = node("div", "source-row");
      if (highlight && number >= highlight.start_line && number <= highlight.end_line) line.dataset.highlight = "true";
      line.append(node("span", "source-row-number", String(number)), node("span", "source-row-text", lines[number - 1]));
      rows.push(line);
    }
    viewer.replaceChildren(...rows);
    viewer.scrollTop = 0;
    prev.disabled = start <= 1;
    next.disabled = end >= lines.length;
    page.textContent = `${start}–${end} of ${lines.length}`;
  }
}

function editSource(source, path, onSaved) {
  const content = field("Source text", "content", { value: source.content, rows: 13, required: true, max: MAX_SOURCE_LENGTH });
  const note = node("p", "field-note", "Existing handoffs keep the excerpts they cited. A new revision marks those citations as changed.");
  formDialog(`Revise “${source.name}”`, "Save revision", [note, content.wrapper], async (data) => {
    const updated = await request(path, "PUT", { content: data.get("content"), expected_revision: source.revision });
    closeDialog();
    notice(updated.revision === source.revision ? "Source text is unchanged." : `Saved revision ${updated.revision} of “${updated.name}”.`);
    await onSaved();
  });
}

function archiveSource(source, path, onSaved) {
  const note = node("p", "field-note", "Archived sources are removed from the project’s active list and generation options. Existing citations can still open earlier revisions.");
  formDialog(`Archive “${source.name}”?`, "Archive source", [note], async () => {
    await request(path, "DELETE");
    closeDialog();
    notice(`Archived “${source.name}”.`);
    await onSaved();
  });
}

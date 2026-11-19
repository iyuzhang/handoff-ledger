import { badge, button, field, node, shortDate } from "./ui.js";

const STATUSES = ["pending", "verified", "blocked"];
const MAX_STEPS = 40;

export function createEditor(record, actions) {
  const editable = record.state === "draft";
  const panel = node(editable ? "form" : "article");
  const draft = structuredClone(record);
  const baseline = new Map(record.steps.map((step) => [step.id, step]));
  let sourceRevisions = new Map(actions.sources.map((source) => [source.id, source.revision]));
  const evidenceIndexes = new WeakMap();
  for (const step of draft.steps) step.evidence.forEach((quote, index) => evidenceIndexes.set(quote, index));
  let selected = draft.steps.find((step) => step.id === actions.selectedStepId) || draft.steps[0] || null;
  let dirty = false;
  let saving = false;
  const toolbar = buildToolbar(record, actions, editable);
  const title = node("h2", "", record.title);
  const goal = node("p", "read-value", record.goal);
  const overview = node("div", "record-heading");
  overview.append(toolbar.element, title, goal, node("p", "record-meta", `Revision ${record.revision} · Updated ${shortDate(record.updated_at)}`));

  const details = buildDetails(draft, editable, markChanged, title, goal);
  if (record.parent_handoff_id) {
    overview.append(button("Open previous handoff", "quiet-link ancestor-link", () => actions.openParent(record.parent_handoff_id)));
  }
  if (editable && record.summary) {
    const summary = node("p", "record-summary", record.summary);
    overview.append(summary);
    details.addEventListener("toggle", () => {
      summary.textContent = draft.summary;
      summary.hidden = details.open;
    });
  }
  const list = node("div", "steps");
  const stepHead = node("div", "section-header");
  stepHead.append(node("h3", "", "Steps"));
  const add = button("+ Add step", "button compact", () => {
    if (saving || draft.steps.length >= MAX_STEPS) return;
    const step = { title: "", instruction: "", verify: "", status: "pending", notes: "", evidence: [] };
    draft.steps.push(step);
    selected = step;
    markChanged();
    renderSteps();
    list.lastElementChild.querySelector("input")?.focus();
  });
  if (editable) stepHead.append(add);
  const error = node("p", "form-error");
  error.hidden = true;
  error.setAttribute("role", "alert");
  const tail = node("div", "form-actions");
  if (editable) {
    const bottomSave = node("button", "button primary", "Save changes");
    bottomSave.type = "submit";
    bottomSave.disabled = true;
    tail.append(bottomSave);
  }
  panel.append(overview);
  if (!editable) panel.append(buildReview(record));
  panel.append(details, stepHead, list, error, tail);

  panel.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!dirty || saving || !editable) return;
    saving = true;
    panel.inert = true;
    error.hidden = true;
    syncButtons();
    try {
      const steps = draft.steps.map((step) => {
        const { id, title, instruction, verify, status, notes } = step;
        const payload = { ...(id ? { id } : {}), title, instruction, verify, status, notes };
        if (evidenceEdited(step)) {
          payload.evidence = step.evidence.map((quote) => {
            const { source_id, revision, start_line, end_line } = quote;
            const originalIndex = evidenceIndexes.get(quote);
            return {
              source_id, revision, start_line, end_line,
              ...(originalIndex === undefined ? {} : { existing_index: originalIndex }),
            };
          });
        }
        return payload;
      });
      await actions.save({
        expected_revision: record.revision, title: draft.title, goal: draft.goal,
        summary: draft.summary, gaps: draft.gaps, steps,
      });
      dirty = false;
    } catch (exception) {
      showError(exception.message);
    } finally {
      saving = false;
      panel.inert = false;
      syncButtons();
    }
  });
  renderSteps();

  return {
    element: panel,
    isDirty: () => dirty || saving,
    isSaving: () => saving,
    refreshSources,
  };

  function markChanged() {
    dirty = true;
    syncButtons();
  }

  function syncButtons() {
    toolbar.save.disabled = !dirty || saving;
    toolbar.save.textContent = saving ? "Saving…" : "Save changes";
    toolbar.seal.disabled = dirty || saving;
    toolbar.seal.title = dirty ? "Save your changes before sealing" : "";
    toolbar.deleteDraft.disabled = saving;
    const bottomSave = tail.querySelector("button");
    if (bottomSave) {
      bottomSave.disabled = !dirty || saving;
      bottomSave.textContent = toolbar.save.textContent;
    }
    add.disabled = saving || draft.steps.length >= MAX_STEPS;
    toolbar.label.textContent = dirty ? "Unsaved changes" : "";
  }

  function hasDrift(step) {
    return step.evidence.some((quote) => quote.stale || sourceRevisions.get(quote.source_id) !== quote.revision);
  }

  function refreshSources(sources) {
    sourceRevisions = new Map(sources.map((source) => [source.id, source.revision]));
    draft.steps.forEach((step, index) => {
      const flag = list.children[index]?.querySelector(".step-drift");
      if (flag) flag.hidden = !hasDrift(step);
    });
  }

  function evidenceEdited(step) {
    const original = baseline.get(step.id)?.evidence || [];
    return step.evidence.length !== original.length || step.evidence.some((quote, index) => evidenceIndexes.get(quote) !== index);
  }

  function renderSteps() {
    const cards = draft.steps.map((step, index) => createStepCard(step, {
      index,
      size: draft.steps.length,
      selected: selected === step,
      editable,
      original: baseline.get(step.id),
      citationChanged: evidenceEdited(step),
      stale: hasDrift(step),
      select: () => selectStep(step, true),
      changed: markChanged,
      move: (offset) => {
        if (saving) return;
        draft.steps.splice(index, 1);
        draft.steps.splice(index + offset, 0, step);
        markChanged();
        renderSteps();
        list.children[index + offset]?.querySelector(".step-anchor")?.focus();
      },
      remove: () => {
        if (saving || !window.confirm("Remove this step from the draft?")) return;
        draft.steps.splice(index, 1);
        if (selected === step) selected = draft.steps[index] || draft.steps[index - 1] || null;
        markChanged();
        renderSteps();
        (list.children[index]?.querySelector(".step-anchor") || add)?.focus();
      },
    }));
    if (!cards.length) cards.push(node("p", "empty-text", "Add a step with an instruction and a way to verify it."));
    list.replaceChildren(...cards);
    selectStep(selected);
    syncButtons();
  }

  function selectStep(step, bringIntoView = false) {
    selected = step;
    Array.from(list.children).forEach((card, index) => {
      const isSelected = draft.steps[index] != null && draft.steps[index] === step;
      card.dataset.selected = String(isSelected);
      card.querySelector(".step-anchor")?.setAttribute("aria-pressed", String(isSelected));
    });
    const changeEvidence = editable && selected ? (quotes) => {
      if (saving) return;
      step.evidence = quotes;
      markChanged();
      renderSteps();
    } : null;
    actions.selectStep(step, bringIntoView, changeEvidence);
  }

  function showError(message) {
    error.textContent = message;
    error.hidden = false;
    error.scrollIntoView({ block: "nearest" });
  }
}

function buildToolbar(record, actions, editable) {
  const element = node("div", "record-toolbar");
  const states = node("div", "record-actions");
  const label = node("span", "step-note");
  label.setAttribute("role", "status");
  states.append(badge(record.state));
  if (record.outcome) states.append(badge(record.outcome === "ready" ? "verified" : "blocked", record.outcome === "ready" ? "Ready" : "Blocked"));
  states.append(label);
  const controls = node("div", "record-actions");
  const save = node("button", "button primary", "Save changes");
  save.type = "submit";
  const seal = button("Seal handoff", "button", actions.seal);
  const deleteDraft = button("Delete draft", "button danger", actions.remove);
  const markdown = button("Markdown ↓", "button", () => actions.export("markdown"));
  const json = button("JSON ↓", "button", () => actions.export("json"));
  markdown.setAttribute("aria-label", "Export Markdown");
  json.setAttribute("aria-label", "Export JSON");
  controls.append(markdown, json);
  if (editable) controls.append(deleteDraft, seal, save);
  else if (actions.followUp) {
    const followUp = button("Follow-up draft", "button primary", async () => {
      followUp.disabled = true;
      try { await actions.followUp(); }
      finally { followUp.disabled = false; }
    });
    controls.append(followUp);
  }
  element.append(states, controls);
  return { element, save, seal, deleteDraft, label };
}

function buildDetails(record, editable, changed, title, goal) {
  const element = node("details", "record-fields");
  const body = node("div", "details-content");
  const overview = node("summary", "", editable ? "Handoff details and gaps" : "Summary and gaps");
  element.append(overview, body);
  element.open = !editable;
  if (!editable) {
    body.append(readField("Summary", record.summary), readField("Open questions", record.gaps.join("\n")));
    return element;
  }

  const fields = [
    { label: "Title", key: "title", max: 160, required: true, updated: title },
    { label: "Goal", key: "goal", max: 2000, rows: 2, required: true, updated: goal },
    { label: "Summary", key: "summary", max: 5000, rows: 3 },
  ];
  for (const info of fields) {
    const input = field(info.label, info.key, { ...info, value: record[info.key] });
    input.control.addEventListener("input", () => {
      record[info.key] = input.control.value;
      if (info.updated) info.updated.textContent = input.control.value;
      changed();
    });
    body.append(input.wrapper);
  }
  const gaps = field("Open questions (one per line)", "gaps", { value: record.gaps.join("\n"), rows: 3, max: 40039 });
  gaps.control.addEventListener("input", () => {
    record.gaps = gaps.control.value.split("\n").map((line) => line.trim()).filter(Boolean);
    const invalid = record.gaps.length > 40 || record.gaps.some((gap) => gap.length > 1000);
    gaps.control.setCustomValidity(invalid ? "Use at most 40 questions, each 1,000 characters or fewer." : "");
    changed();
  });
  body.append(gaps.wrapper);
  element.addEventListener("invalid", () => { element.open = true; }, true);
  return element;
}

function createStepCard(step, options) {
  const card = node("article", "step-card");
  const toolbar = node("div", "step-toolbar");
  const caption = node("div", "record-actions");
  const drift = badge("stale", "Source changed");
  drift.classList.add("step-drift");
  drift.hidden = !options.stale;
  caption.append(node("strong", "", `Step ${options.index + 1}`), drift);
  const buttons = node("div", "record-actions");
  const evidence = button(`Evidence · ${step.evidence.length}`, "button compact step-anchor", options.select);
  evidence.setAttribute("aria-label", `Show evidence for step ${options.index + 1} (${step.evidence.length} excerpts)`);
  buttons.append(evidence);
  if (options.editable) buttons.append(...stepActions(options));
  toolbar.append(caption, buttons);
  card.append(toolbar);
  if (!options.editable) {
    card.append(node("h3", "", step.title), badge(step.status),
      readField("Instruction", step.instruction), readField("How to verify", step.verify), readField("Reviewer notes", step.notes));
    return card;
  }
  card.append(buildStepFields(step, options));
  return card;
}

function stepActions({ index, size, move, remove }) {
  const up = button("↑", "button compact", () => move(-1));
  up.disabled = index === 0;
  up.setAttribute("aria-label", `Move step ${index + 1} up`);
  const down = button("↓", "button compact", () => move(1));
  down.disabled = index === size - 1;
  down.setAttribute("aria-label", `Move step ${index + 1} down`);
  const erase = button("Remove", "button compact danger", remove);
  erase.setAttribute("aria-label", `Remove step ${index + 1}`);
  return [up, down, erase];
}

function buildStepFields(step, { index, original, changed, citationChanged }) {
  const group = node("div", "step-fields");
  const review = node("label", "field");
  const status = node("select", "step-status");
  status.setAttribute("aria-label", `Review status for step ${index + 1}`);
  for (const value of STATUSES) {
    const option = node("option", "", value[0].toUpperCase() + value.slice(1));
    option.value = value;
    status.append(option);
  }
  status.value = step.status;
  const hint = node("span", "step-note", "Save the edited step before reviewing it again.");
  hint.hidden = true;
  review.append(node("span", "", "Review status"), status, hint);

  const definitions = [
    ["title", "Step title", 0, 160],
    ["instruction", "Instruction", 4, 3000],
    ["verify", "How to verify", 4, 3000],
    ["notes", "Reviewer notes", 2, 3000],
  ];
  for (const [key, label, rows, max] of definitions) {
    const input = field(label, `${key}-${index + 1}`, { value: step[key], required: key !== "notes", rows, max });
    input.control.addEventListener("input", () => {
      step[key] = input.control.value;
      syncReviewState();
      changed();
    });
    group.append(input.wrapper);
  }
  status.addEventListener("change", () => {
    step.status = status.value;
    changed();
  });
  group.append(review);
  syncReviewState();
  return group;

  function syncReviewState() {
    const textChanged = original && ["title", "instruction", "verify"].some((key) => step[key] !== original[key]);
    const requiresSave = Boolean((textChanged || citationChanged) && original && original.status !== "pending");
    if (requiresSave) step.status = "pending";
    status.value = step.status;
    status.disabled = requiresSave;
    hint.hidden = !requiresSave;
  }
}

function buildReview(record) {
  const block = node("div", "reviewer-block");
  const date = shortDate(record.sealed_at);
  block.append(node("strong", "", `Sealed by ${record.reviewer}${date ? ` · ${date}` : ""}`));
  if (record.review_notes) block.append(readField("Seal notes", record.review_notes));
  return block;
}

function readField(label, text) {
  const wrapper = node("div", "field");
  wrapper.append(node("strong", "", label), node("p", "read-value", text));
  return wrapper;
}

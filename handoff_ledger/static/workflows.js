import { button, closeDialog, field, formDialog, node, notice, projectPath, request, showDialog } from "./ui.js";

export function projectDialog(project, onSaved) {
  const name = field("Project name", "name", { value: project?.name, required: true, max: 160, placeholder: "e.g. Support operations" });
  const description = field("Description (optional)", "description", { value: project?.description, rows: 3, max: 2000 });
  formDialog(project ? "Edit project details" : "Create a project", project ? "Save details" : "Create project", [name.wrapper, description.wrapper], async (data) => {
    const updated = await request(project ? projectPath(project.id) : "/api/projects", project ? "PATCH" : "POST", {
      name: data.get("name"), description: data.get("description"),
    });
    closeDialog();
    await onSaved(updated);
  });
}

export function chooseHandoff({ project, sources, config, activeJob, openDraft, watchJob }) {
  const choices = node("div", "dialog-form");
  const manual = node("div", "choice");
  const draft = button("Start a manual draft", "button", () => createHandoff(project, [], false, openDraft));
  manual.append(draft, node("p", "field-note", "Enter the steps and reviewer checks yourself."));
  const generation = node("div", "choice");
  const generate = button("Generate from sources", "button primary", () => createHandoff(project, sources, true, watchJob));
  const unavailable = activeJob ? "A generation job is already running for this project."
    : !config?.model_configured ? "Configure a model connection to use generation."
      : !sources.length ? "Add a source to the project before generating." : "";
  generate.disabled = Boolean(unavailable);
  generation.append(generate, node("p", "field-note", unavailable || "Choose exactly which documents are sent to the model."));
  choices.append(manual, generation);
  showDialog("New handoff", choices);
}

export function sealDialog(record, stale, path, onSaved) {
  const pending = record.steps.filter((step) => step.status === "pending").length;
  if (!record.steps.length || pending) {
    const reason = record.steps.length ? `Review and save the ${pending} pending ${pending === 1 ? "step" : "steps"} before sealing.` : "Add and save at least one step before sealing.";
    const body = node("div", "dialog-form");
    body.append(node("p", "read-value", reason), button("Return to draft", "button", closeDialog));
    showDialog("Review incomplete", body);
    return;
  }

  const blocked = record.steps.some((step) => step.status === "blocked");
  const reviewer = field("Reviewer name", "reviewer", { required: true, max: 160 });
  const needsNotes = blocked || stale || Boolean(record.gaps.length);
  const notes = field(needsNotes ? "Seal notes (required)" : "Seal notes (optional)", "review_notes", { rows: 4, max: 3000, required: needsNotes });
  const reasons = [blocked && "blocked steps", stale && "changed sources", record.gaps.length > 0 && "open questions"].filter(Boolean);
  const summary = blocked
    ? "The sealed handoff will record a blocked outcome."
    : "The sealed handoff will record a ready outcome.";
  const rationale = needsNotes ? ` Address ${formatList(reasons)} in the seal notes.` : "";
  const message = node("p", "read-value", `${summary}${rationale} Sealing makes this revision read-only.`);
  formDialog("Seal handoff", "Seal handoff", [message, reviewer.wrapper, notes.wrapper], async (data) => {
    const sealed = await request(`${path}/seal`, "POST", {
      expected_revision: record.revision, reviewer: data.get("reviewer"), review_notes: data.get("review_notes"),
    });
    closeDialog();
    notice(`Handoff sealed with a ${sealed.outcome} outcome.`);
    await onSaved(sealed);
  });
}

export function deleteDialog(record, path, onDeleted) {
  const note = node("p", "read-value", `Delete “${record.title}” and its recorded steps. This action is permanent.`);
  formDialog("Delete this draft?", "Delete draft", [note], async () => {
    await request(path, "DELETE");
    closeDialog();
    notice("Draft deleted.");
    await onDeleted();
  });
}

export function modelDialog(config, refresh) {
  const container = node("div", "dialog-form");
  const message = config?.model_configured ? `Configured model: ${config.model || "OpenAI-compatible endpoint"}.`
    : "Set LLM_BASE_URL and LLM_MODEL in the server environment. Use LLM_API_KEY when the endpoint requires authentication, then restart the server.";
  const note = node("p", "field-note", "Manual drafting and review work without a model connection. Generation sends only the sources selected in its form.");
  const controls = node("div", "form-actions");
  controls.append(button("Refresh status", "button", refresh), button("Done", "button primary", closeDialog));
  container.append(node("p", "read-value", message), note, controls);
  showDialog("Model connection", container);
}

function createHandoff(project, sources, model, onCreated) {
  const title = field("Handoff title", "title", { required: true, max: 160, placeholder: "e.g. Transfer the weekly support rotation" });
  const goal = field("Goal", "goal", { rows: 3, required: true, max: 2000, placeholder: "What should the next person be able to do?" });
  const fields = [title.wrapper, goal.wrapper];
  if (model) fields.push(sourceChecklist(sources));
  formDialog(model ? "Generate a handoff" : "Start a manual draft", model ? "Generate draft" : "Create draft", fields, async (data) => {
    const sourceIds = data.getAll("source_ids");
    if (model && (!sourceIds.length || sourceIds.length > 16)) {
      throw new Error("Choose between 1 and 16 sources for generation.");
    }
    const details = { title: data.get("title"), goal: data.get("goal") };
    const created = await request(projectPath(project.id, model ? "/jobs" : "/handoffs"), "POST", model ? { ...details, source_ids: sourceIds } : details);
    closeDialog();
    await onCreated(created);
  });
}

function sourceChecklist(sources) {
  const container = node("fieldset", "checkbox-list");
  container.append(node("legend", "", "Sources to send to the model"));
  const count = node("p", "field-note", "Select up to 16 sources, with a combined limit of 80,000 characters.");
  container.append(count);
  for (const source of sources) {
    const label = node("label");
    const checkbox = node("input");
    checkbox.type = "checkbox";
    checkbox.name = "source_ids";
    checkbox.value = source.id;
    label.append(checkbox, node("span", "", `${source.name} · r${source.revision}`));
    container.append(label);
  }
  return container;
}

function formatList(items) {
  return new Intl.ListFormat("en", { style: "long", type: "conjunction" }).format(items);
}

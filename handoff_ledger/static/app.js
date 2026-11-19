import { pinCitation } from "./evidence.js";
import { createEditor } from "./record.js";
import { importSource, openSource, renderContext } from "./sources.js";
import { badge, button, byId, initUI, node, notice, projectPath, request, shortDate } from "./ui.js";
import { chooseHandoff, deleteDialog, modelDialog, projectDialog, sealDialog } from "./workflows.js";

const JOB_POLL_MS = 1600;
const state = {
  config: null, projects: [], project: null, sources: [], handoffs: [], jobs: [],
  record: null, editor: null, step: null, changeEvidence: null, routeVersion: 0, recordVersion: 0,
  poll: null,
};

initUI();
bindWorkspace();
run(boot);

async function boot() {
  const config = refreshModel().catch((error) => notice(error.message, true));
  state.projects = await request("/api/projects");
  const query = new URLSearchParams(window.location.search);
  const pinned = state.projects.find((item) => item.id === query.get("project"));
  const project = pinned || state.projects[0];
  if (project) await selectProject(project, query.get("handoff"));
  await config;
}

function bindWorkspace() {
  for (const action of document.querySelectorAll('[data-action="new-project"]')) {
    action.addEventListener("click", () => {
      if (!confirmSwitch()) return;
      projectDialog(null, async (project) => {
        state.projects = [project, ...state.projects];
        await run(() => selectProject(project));
      });
    });
  }
  byId("project-select").addEventListener("change", async (event) => {
    const current = state.project;
    const project = state.projects.find((item) => item.id === event.target.value);
    if (project && confirmSwitch()) await run(() => selectProject(project));
    event.target.value = state.project?.id || current?.id || "";
  });
  document.querySelector('[data-action="edit-project"]').addEventListener("click", () => {
    projectDialog(state.project, async (project) => {
      state.projects = state.projects.map((item) => item.id === project.id ? project : item);
      state.project = project;
      renderProject();
      notice("Project details saved.");
    });
  });
  document.querySelector('[data-action="new-handoff"]').addEventListener("click", newHandoff);
  document.querySelector('[data-action="refresh-jobs"]').addEventListener("click", () => run(() => refreshJobs(state.project.id)));
  byId("model-status").addEventListener("click", showModel);
  window.addEventListener("beforeunload", (event) => {
    if (!state.editor?.isDirty()) return;
    event.preventDefault();
    event.returnValue = true;
  });
}

async function selectProject(project, requestedHandoff = null) {
  const version = ++state.routeVersion;
  const root = projectPath(project.id);
  const [sources, handoffs, jobs] = await Promise.all([request(`${root}/sources`), request(`${root}/handoffs`), request(`${root}/jobs`)]);
  if (version !== state.routeVersion) return;

  stopPoll();
  state.project = project;
  state.sources = sources;
  state.handoffs = handoffs;
  state.jobs = jobs;
  byId("onboarding").hidden = true;
  byId("workspace").hidden = false;
  updateRecord(null);
  renderProject();
  renderJobs();
  syncPoll();
  const current = handoffs.find((item) => item.id === requestedHandoff) || handoffs[0];
  if (current) await selectHandoff(current.id);
}

async function selectHandoff(id) {
  const project = state.project.id;
  const version = ++state.recordVersion;
  const record = await request(projectPath(project, `/handoffs/${encodeURIComponent(id)}`));
  if (state.project?.id === project && state.recordVersion === version) updateRecord(record);
}

function updateRecord(record) {
  state.recordVersion += 1;
  const previous = state.record?.id === record?.id ? state.step?.id : null;
  state.record = record;
  state.step = null;
  state.changeEvidence = null;
  state.editor = null;
  renderHandoffList();
  writeLocation();

  if (!record) {
    const empty = node("section", "record-empty");
    empty.append(node("h2", "", "Prepare a handoff"), node("p", "empty-text", "Start with your own steps or generate a draft from the documents in this project."));
    empty.append(button("+ New handoff", "button primary", newHandoff));
    byId("record").replaceChildren(empty);
    renderSidebar();
    return;
  }

  const root = projectPath(record.project_id, `/handoffs/${encodeURIComponent(record.id)}`);
  state.editor = createEditor(record, {
    selectedStepId: previous,
    sources: state.sources,
    openParent: (id) => { if (confirmSwitch()) run(() => selectHandoff(id)); },
    selectStep: (step, reveal, changeEvidence) => {
      state.step = step;
      state.changeEvidence = changeEvidence;
      renderSidebar(reveal);
    },
    save: async (body) => {
      const updated = await request(root, "PUT", body);
      if (state.record?.id === updated.id) updateRecord(updated);
      notice("Draft saved.");
      await run(() => refreshHandoffList(record.project_id));
    },
    export: (format) => run(() => exportRecord(root, record, format)),
    seal: () => sealDialog(record, hasStaleEvidence(record), root, async (sealed) => {
      updateRecord(sealed);
      await run(() => refreshHandoffList(record.project_id));
    }),
    remove: () => deleteDialog(record, root, async () => {
      updateRecord(null);
      await run(() => refreshHandoffList(record.project_id));
    }),
    followUp: () => run(async () => {
      const draft = await request(`${root}/follow-up`, "POST", {});
      notice("Follow-up draft created. Review each step before sealing.");
      if (state.project.id === record.project_id) updateRecord(draft);
      await refreshHandoffList(record.project_id);
    }),
  });
  byId("record").replaceChildren(state.editor.element);
}

function renderProject() {
  const project = state.project;
  const control = byId("project-select");
  control.replaceChildren(...state.projects.map((item) => {
    const option = node("option", "", item.name);
    option.value = item.id;
    return option;
  }));
  control.value = project.id;
  const title = node("div");
  title.append(node("h1", "", project.name));
  if (project.description) title.append(node("p", "empty-text", project.description));
  byId("project-header").replaceChildren(title, button("+ New handoff", "button primary", newHandoff));
  renderSidebar();
}

function renderHandoffList() {
  const list = byId("handoff-list");
  if (state.handoffs.length === 0) {
    list.replaceChildren(node("p", "empty-text", "No handoffs yet."));
    return;
  }
  list.replaceChildren(...state.handoffs.map((item) => {
    const link = button("", "handoff-link", () => {
      if (item.id === state.record?.id || !confirmSwitch()) return;
      run(() => selectHandoff(item.id));
    });
    if (item.id === state.record?.id) link.setAttribute("aria-current", "true");
    const status = item.state === "sealed" ? "Sealed" : "Draft";
    const outcome = item.outcome === "blocked" ? " · Blocked" : item.outcome === "ready" ? " · Ready" : "";
    link.append(node("strong", "", item.title), node("small", "", `${status}${outcome} · r${item.revision}`));
    return link;
  }));
}

function renderSidebar(reveal = false) {
  const { changeEvidence, step, sources, project } = state;
  renderContext(byId("context"), state.sources, state.step, {
    add: () => importSource(project, () => run(() => refreshSources(project.id))),
    pin: changeEvidence ? () => pinCitation(project, sources, step.evidence, (quote) => {
      changeEvidence([...step.evidence, quote]);
    }) : null,
    remove: changeEvidence ? (quote) => {
      changeEvidence(step.evidence.filter((item) => item !== quote));
      byId("evidence-heading").focus({ preventScroll: true });
    } : null,
    open: (source) => run(() => openSource(state.project, source.id, { active: true, onSaved: () => run(() => refreshSources(source.project_id)) })),
    openExcerpt: (quote) => {
      const project = state.project;
      const active = state.sources.some((source) => source.id === quote.source_id);
      run(() => openSource(project, quote.source_id, { active, quote, onSaved: () => run(() => refreshSources(project.id)) }));
    },
  });
  if (reveal && window.matchMedia("(max-width: 900px)").matches) {
    const heading = byId("evidence-heading");
    heading.focus({ preventScroll: true });
    heading.scrollIntoView({ block: "start" });
  }
}

function renderJobs() {
  const section = byId("job-section");
  section.hidden = !state.jobs.length;
  byId("job-list").replaceChildren(...state.jobs.slice(0, 6).map((job) => {
    const row = node("div", "job");
    row.append(badge(job.state, job.state === "succeeded" ? "Draft created" : ""));
    row.append(node("time", "", shortDate(job.created_at)));
    if (job.error) row.append(node("p", "empty-text", job.error));
    if (job.handoff_id) row.append(button("Open draft", "button compact", () => {
      if (job.handoff_id !== state.record?.id && confirmSwitch()) run(() => selectHandoff(job.handoff_id));
    }));
    return row;
  }));
}

function newHandoff() {
  if (!confirmSwitch()) return;
  const project = state.project;
  chooseHandoff({
    project, sources: state.sources, config: state.config, activeJob: state.jobs.some(isActive),
    openDraft: async (record) => {
      updateRecord(record);
      await run(() => refreshHandoffList(project.id));
    },
    watchJob: (job) => {
      state.jobs = [job, ...state.jobs];
      renderJobs();
      syncPoll();
      notice("Generation queued. You can keep working while it runs.");
    },
  });
}

async function refreshJobs(projectId) {
  const jobs = await request(projectPath(projectId, "/jobs"));
  if (state.project?.id !== projectId) return;
  const activeIds = new Set(state.jobs.filter(isActive).map((job) => job.id));
  state.jobs = jobs;
  renderJobs();
  const completed = jobs.find((job) => activeIds.has(job.id) && job.state === "succeeded");
  if (completed) {
    await refreshHandoffList(projectId);
    if (state.project?.id === projectId && completed.handoff_id && !state.editor?.isDirty()) await selectHandoff(completed.handoff_id);
    notice("Generation finished. Review the draft before sealing.");
  }
  const failed = jobs.find((job) => activeIds.has(job.id) && job.state === "failed");
  if (failed) notice(failed.error || "Generation failed. Check the model connection and start a new job.", true);
  syncPoll();
}

async function refreshSources(projectId) {
  const sources = await request(projectPath(projectId, "/sources"));
  if (state.project?.id !== projectId) return;
  state.sources = sources;
  state.editor?.refreshSources(sources);
  renderSidebar();
}

async function refreshHandoffList(projectId) {
  const handoffs = await request(projectPath(projectId, "/handoffs"));
  if (state.project?.id !== projectId) return;
  state.handoffs = handoffs;
  renderHandoffList();
}

async function refreshModel() {
  state.config = await request("/api/config");
  const status = byId("model-status");
  status.dataset.state = state.config.model_configured ? "on" : "off";
  status.lastElementChild.textContent = state.config.model_configured ? "Model configured" : "Model not configured";
}

async function showModel() {
  modelDialog(state.config, () => run(async () => {
    await refreshModel();
    if (byId("dialog").open) showModel();
  }));
}

async function exportRecord(root, record, format) {
  if (state.editor?.isDirty() && !window.confirm("Export the last saved revision? Your unsaved edits will remain in the editor.")) return;
  const response = await fetch(`${root}/export?format=${format}`, { cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Export failed (HTTP ${response.status}). Retry from the saved handoff.`);
  }
  const href = URL.createObjectURL(await response.blob());
  const disposition = response.headers.get("content-disposition") || "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1];
  const link = node("a");
  link.href = href;
  link.download = filename || `handoff-${record.id}.${format === "markdown" ? "md" : "json"}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
  notice(`Exported revision ${record.revision}.`);
}

function syncPoll() {
  stopPoll();
  if (!state.jobs.some(isActive)) return;
  const projectId = state.project.id;
  state.poll = setTimeout(async () => {
    state.poll = null;
    try {
      await refreshJobs(projectId);
    } catch (exception) {
      if (state.project?.id !== projectId) return;
      notice(`Could not refresh generation. ${exception.message} Use the refresh button to reconnect.`, true);
    }
  }, JOB_POLL_MS);
}

function stopPoll() {
  clearTimeout(state.poll);
  state.poll = null;
}

function isActive(job) {
  return job.state === "queued" || job.state === "running";
}

function hasStaleEvidence(record) {
  return record.steps.some((step) => step.evidence.some((quote) => {
    const active = state.sources.find((source) => source.id === quote.source_id);
    return quote.stale || !active || active.revision !== quote.revision;
  }));
}

function confirmSwitch() {
  if (state.editor?.isSaving()) {
    notice("Wait for the draft to finish saving.");
    return false;
  }
  return !state.editor?.isDirty() || window.confirm("Leave this draft without saving your changes?");
}

function writeLocation() {
  const url = new URL(window.location.href);
  url.searchParams.set("project", state.project.id);
  if (state.record) url.searchParams.set("handoff", state.record.id);
  else url.searchParams.delete("handoff");
  window.history.replaceState(null, "", url);
}

async function run(work) {
  try {
    await work();
  } catch (exception) {
    notice(exception.message, true);
  }
}

export function byId(id) {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing interface element: ${id}`);
  return element;
}

export function node(tag, classes = "", content = "") {
  const element = document.createElement(tag);
  if (classes) element.className = classes;
  element.textContent = content;
  return element;
}

export function button(text, classes, listener) {
  const element = node("button", classes, text);
  element.type = "button";
  element.addEventListener("click", listener);
  return element;
}

export function field(label, name, {
  value = "", rows = 0, max = Infinity, required = false, placeholder = "",
} = {}) {
  const wrapper = node("label", "field");
  const control = node(rows ? "textarea" : "input");
  if (rows) control.rows = rows;
  else control.type = "text";
  control.name = name;
  control.value = value;
  control.required = required;
  if (Number.isFinite(max)) control.maxLength = max;
  control.placeholder = placeholder;
  wrapper.append(node("span", "", label), control);
  return { wrapper, control };
}

export function badge(state, label = "") {
  const element = node("span", "status-badge", label || state.replace(/^./, (first) => first.toUpperCase()));
  element.dataset.state = state;
  return element;
}

export function shortDate(value) {
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(time);
}

export function projectPath(projectId, relative = "") {
  return `/api/projects/${encodeURIComponent(projectId)}${relative}`;
}

export async function request(path, method = "GET", body) {
  const headers = body === undefined ? {} : { "Content-Type": "application/json" };
  let response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  } catch {
    throw new Error("The workspace server could not be reached. Check that it is running and retry.");
  }
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (response.ok && payload !== null) return payload;
  const detail = payload?.detail;
  if (typeof detail === "string") throw new Error(detail);
  if (Array.isArray(detail)) {
    const messages = detail.map((issue) => {
      if (typeof issue.msg !== "string") return "";
      const input = Array.isArray(issue.loc) ? issue.loc.slice(1).join(" / ").replaceAll("_", " ") : "";
      return input ? `${input} — ${issue.msg}` : issue.msg;
    }).filter(Boolean);
    if (messages.length) throw new Error(messages.join(". "));
  }
  throw new Error(`The server returned HTTP ${response.status}. Retry or check its logs.`);
}

export function notice(text, isError = false) {
  const element = byId("notice");
  byId("notice-message").textContent = text;
  element.dataset.level = isError ? "error" : "info";
  element.setAttribute("role", isError ? "alert" : "status");
  element.hidden = false;
}

export function showDialog(title, content, size = "") {
  const dialog = byId("dialog");
  byId("dialog-title").textContent = title;
  byId("dialog-content").replaceChildren(content);
  dialog.dataset.size = size;
  if (!dialog.open) dialog.showModal();
}

export function closeDialog() {
  byId("dialog").close();
}

export function formDialog(title, submitLabel, fields, submit) {
  const form = node("form", "dialog-form");
  const error = node("p", "form-error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  const actions = node("div", "form-actions");
  const cancel = button("Cancel", "button", closeDialog);
  const save = node("button", "button primary", submitLabel);
  save.type = "submit";
  actions.append(cancel, save);
  form.append(...fields, error, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (save.disabled) return;
    error.hidden = true;
    save.disabled = true;
    cancel.disabled = true;
    byId("dialog-close").disabled = true;
    byId("dialog").dataset.busy = "true";
    save.textContent = "Working…";
    try {
      await submit(new FormData(form));
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
    } finally {
      save.textContent = submitLabel;
      save.disabled = false;
      cancel.disabled = false;
      byId("dialog-close").disabled = false;
      delete byId("dialog").dataset.busy;
    }
  });
  showDialog(title, form);
  return { form, error };
}

export function initUI() {
  byId("dialog-close").addEventListener("click", closeDialog);
  byId("dialog").addEventListener("cancel", (event) => {
    if (event.currentTarget.dataset.busy) event.preventDefault();
  });
  byId("dismiss-notice").addEventListener("click", () => { byId("notice").hidden = true; });
}

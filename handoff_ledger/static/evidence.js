import { closeDialog, field, formDialog, node, projectPath, request } from "./ui.js";

const MAX_QUOTE_LENGTH = 3000;

export function pinCitation(project, sources, existing, onPin) {
  const picker = node("label", "field", "Source");
  const selected = node("select");
  for (const source of sources) {
    const option = node("option", "", `${source.name} · Revision ${source.revision}`);
    option.value = source.id;
    selected.append(option);
  }
  picker.append(selected);
  const start = lineField("Start line", "start_line");
  const end = lineField("End line", "end_line");
  const rangeFields = node("div", "source-controls");
  rangeFields.append(start.wrapper, end.wrapper);
  const hint = node("p", "field-note", "Choose a line range to preview it. The selected excerpt is stored when you save the draft.");
  const preview = node("pre", "quote-preview");
  preview.tabIndex = 0;
  preview.setAttribute("aria-label", "Selected source excerpt");
  preview.setAttribute("aria-live", "polite");
  const { error } = formDialog("Pin a source excerpt", "Pin excerpt", [picker, rangeFields, hint, preview], () => {
    const quote = readQuote();
    const isDuplicate = existing.some((item) => item.source_id === quote.source_id && item.revision === quote.revision
      && item.start_line === quote.start_line && item.end_line === quote.end_line && item.excerpt === quote.excerpt);
    if (isDuplicate) throw new Error("That excerpt is already pinned to this step.");
    closeDialog();
    onPin(quote);
  });

  let source = null;
  let lines = [];
  let selection = 0;
  selected.addEventListener("change", load);
  start.control.addEventListener("input", drawPreview);
  end.control.addEventListener("input", drawPreview);
  load();

  async function load() {
    const version = ++selection;
    error.hidden = true;
    source = null;
    preview.textContent = "Loading source…";
    const id = encodeURIComponent(selected.value);
    try {
      const current = await request(projectPath(project.id, `/sources/${id}`));
      if (version !== selection) return;
      source = current;
      lines = source.content.split("\n").slice(0, source.line_count);
      for (const input of [start.control, end.control]) {
        input.max = String(source.line_count);
        input.value = "1";
      }
      hint.textContent = `Choose from ${source.line_count} ${source.line_count === 1 ? "line" : "lines"}. The selected excerpt is stored when you save the draft.`;
      drawPreview();
    } catch (exception) {
      if (version !== selection) return;
      preview.textContent = "";
      error.textContent = exception.message;
      error.hidden = false;
    }
  }

  function drawPreview() {
    try {
      preview.textContent = readQuote().excerpt || "(Blank lines)";
    } catch (exception) {
      preview.textContent = exception.message;
    }
  }

  function readQuote() {
    if (!source) throw new Error("Wait for the source to load.");
    const first = start.control.valueAsNumber;
    const last = end.control.valueAsNumber;
    if (!Number.isInteger(first) || !Number.isInteger(last) || first < 1 || last < first || last > lines.length) {
      throw new Error(`Enter a line range from 1 to ${lines.length}.`);
    }
    const excerpt = lines.slice(first - 1, last).join("\n");
    if (Array.from(excerpt).length > MAX_QUOTE_LENGTH) {
      throw new Error("Choose a shorter range. Each excerpt can contain at most 3,000 characters.");
    }
    return {
      source_id: source.id, source_name: source.name, revision: source.revision,
      start_line: first, end_line: last, excerpt, stale: false,
    };
  }
}

function lineField(label, name) {
  const input = field(label, name, { required: true });
  input.control.type = "number";
  input.control.min = "1";
  input.control.max = "1";
  input.control.value = "1";
  return input;
}

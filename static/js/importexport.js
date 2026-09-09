// Export links and the two-phase import form (preview, then a separate
// explicit commit). Preview never writes anything -- it only stages a row
// in import_run -- so a bad file costs nothing to try.

import { api, postFile } from "./api.js";

export function buildExportLinks() {
  const wrap = document.createElement("div");
  wrap.className = "export-links";

  const heading = document.createElement("h2");
  heading.textContent = "Export";
  wrap.appendChild(heading);

  const jsonLink = document.createElement("a");
  jsonLink.href = "api/export/json";
  jsonLink.className = "export-link-btn";
  jsonLink.textContent = "Export all as JSON (full backup)";
  wrap.appendChild(jsonLink);

  const csvLink = document.createElement("a");
  csvLink.href = "api/export/csv";
  csvLink.className = "export-link-btn";
  csvLink.textContent = "Export all as CSV";
  wrap.appendChild(csvLink);

  return wrap;
}

export function buildBatchExportLink(batchId) {
  const link = document.createElement("a");
  link.href = `api/batches/${batchId}/export/csv`;
  link.className = "export-link-btn";
  link.textContent = "Export this batch as CSV";
  return link;
}

export function buildImportForm() {
  const wrap = document.createElement("div");
  wrap.className = "import-form";

  const heading = document.createElement("h2");
  heading.textContent = "Import";
  wrap.appendChild(heading);

  const hint = document.createElement("p");
  hint.className = "form-hint";
  hint.textContent =
    "CSV or a JSON backup. Only creates batches whose batch number doesn't " +
    "already exist -- an existing batch is never changed by an import.";
  wrap.appendChild(hint);

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = ".csv,.json";
  wrap.appendChild(fileInput);

  const previewBtn = document.createElement("button");
  previewBtn.type = "button";
  previewBtn.textContent = "Preview";
  wrap.appendChild(previewBtn);

  const reportEl = document.createElement("div");
  reportEl.className = "import-report";
  wrap.appendChild(reportEl);

  const commitBtn = document.createElement("button");
  commitBtn.type = "button";
  commitBtn.textContent = "Commit import";
  commitBtn.hidden = true;
  wrap.appendChild(commitBtn);

  const errorBox = document.createElement("div");
  errorBox.className = "form-error";
  wrap.appendChild(errorBox);

  let stagedToken = null;

  function formatFor(file) {
    return file.name.toLowerCase().endsWith(".json") ? "json" : "csv";
  }

  function renderReport(report) {
    reportEl.innerHTML = "";
    const summary = document.createElement("p");
    summary.textContent =
      `${report.rowCount} row(s) · ${report.batchesNew.length} new batch(es): ` +
      `${report.batchesNew.join(", ") || "none"}`;
    reportEl.appendChild(summary);

    if (report.batchesSkippedExisting.length > 0) {
      const skipped = document.createElement("p");
      skipped.className = "import-warning";
      skipped.textContent =
        `Skipped (already exist, unchanged): ${report.batchesSkippedExisting.join(", ")}`;
      reportEl.appendChild(skipped);
    }

    if (report.errors.length > 0) {
      const errHeading = document.createElement("p");
      errHeading.className = "import-errors-heading";
      errHeading.textContent = `${report.errors.length} problem(s) -- fix and re-preview:`;
      reportEl.appendChild(errHeading);
      const list = document.createElement("ul");
      for (const err of report.errors) {
        const li = document.createElement("li");
        li.textContent = err;
        list.appendChild(li);
      }
      reportEl.appendChild(list);
    }
  }

  previewBtn.addEventListener("click", async () => {
    errorBox.textContent = "";
    reportEl.innerHTML = "";
    commitBtn.hidden = true;
    stagedToken = null;

    const file = fileInput.files[0];
    if (!file) {
      errorBox.textContent = "Choose a file first.";
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    formData.append("format", formatFor(file));

    try {
      const result = await postFile("api/import/preview", formData);
      renderReport(result.report);
      if (result.report.errors.length === 0 && result.report.batchesNew.length > 0) {
        stagedToken = result.token;
        commitBtn.hidden = false;
      }
    } catch (e) {
      errorBox.textContent = e.message || "Could not read that file";
    }
  });

  commitBtn.addEventListener("click", async () => {
    if (!stagedToken) return;
    errorBox.textContent = "";
    try {
      const result = await api.post("api/import/commit", { token: stagedToken });
      reportEl.innerHTML = "";
      const done = document.createElement("p");
      done.textContent =
        `Done: ${result.batchesCreated} batch(es) created, ${result.shaftsWritten} shaft(s) written.`;
      reportEl.appendChild(done);
      commitBtn.hidden = true;
      stagedToken = null;
      fileInput.value = "";
    } catch (e) {
      errorBox.textContent = e.message || "Could not commit the import";
    }
  });

  return wrap;
}

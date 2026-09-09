// Batches tab: list (sortable by every column), and the create-batch form.
// Diameter and wood pull-downs are rendered in the order the server
// returns them (sort_order, not alphabetical) -- see repo_lookups.py.

import { api } from "./api.js";
import { buildExportLinks, buildImportForm } from "./importexport.js";
import { attachColumnSort } from "./tablesort.js";

export async function loadLookup(kind) {
  return api.get(`api/lookups/${kind}`);
}

export function optionEl(value, label) {
  const opt = document.createElement("option");
  opt.value = String(value);
  opt.textContent = label;
  return opt;
}

export async function renderBatchList(root) {
  const [batches, diameters, woods, shops] = await Promise.all([
    api.get("api/batches"),
    loadLookup("diameter"),
    loadLookup("wood"),
    loadLookup("shop"),
  ]);

  const wrap = document.createElement("div");
  wrap.className = "view view-batches";

  const heading = document.createElement("h1");
  heading.textContent = "Batches";
  wrap.appendChild(heading);

  wrap.appendChild(buildBatchTable(batches, diameters, woods, shops));
  wrap.appendChild(buildCreateForm());
  wrap.appendChild(buildExportLinks());
  wrap.appendChild(buildImportForm());

  root.appendChild(wrap);
}

// Each column knows how to read a comparable value off a batch row --
// the same function serves as both the cell's display text and its sort
// key here, since a batch row's raw values (numbers, short labels) are
// already exactly what should be compared, unlike shaftinfo.js's tables
// where a formatted display string and its sort value can differ.
function batchColumns(diameters, woods, shops) {
  const diameterLabel = (b) => diameters.find((d) => d.id === b.diameterId)?.label || "Unknown";
  const woodLabel = (b) => woods.find((w) => w.id === b.woodId)?.label || "Unknown";
  const shopLabel = (b) => shops.find((s) => s.id === b.shopId)?.label || "";

  return [
    { label: "Batch", get: (b) => b.batchNo },
    { label: "Spine range", get: (b) => b.nominalSpineLabel || "" },
    { label: "Diameter", get: diameterLabel },
    { label: "Wood", get: woodLabel },
    { label: "Shaft Source", get: shopLabel },
    { label: "Purchased", get: (b) => b.purchaseDate || "" },
    { label: "Shafts", get: (b) => b.expectedCount },
  ];
}

function buildBatchTable(batches, diameters, woods, shops) {
  const columns = batchColumns(diameters, woods, shops);
  const table = document.createElement("table");
  table.className = "batch-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const headerCells = [];
  for (const column of columns) {
    const th = document.createElement("th");
    th.textContent = column.label;
    headRow.appendChild(th);
    headerCells.push(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  table.appendChild(tbody);

  const emptyState = document.createElement("p");
  emptyState.className = "empty-state";
  emptyState.textContent = "No batches yet. Create one below.";
  emptyState.hidden = batches.length > 0;

  function renderRows() {
    tbody.innerHTML = "";
    for (const b of sorter.sortRows(batches)) {
      const tr = document.createElement("tr");
      tr.className = "batch-row";
      for (const col of columns) {
        const td = document.createElement("td");
        td.textContent = String(col.get(b));
        tr.appendChild(td);
      }
      tr.addEventListener("click", () => {
        location.hash = `#/batches/${b.id}`;
      });
      tbody.appendChild(tr);
    }
  }

  const sorter = attachColumnSort(
    headerCells,
    columns.map((c) => ({ sortValue: c.get })),
    renderRows
  );

  renderRows();
  table.after(emptyState);
  return table;
}

function buildCreateForm() {
  const form = document.createElement("form");
  form.className = "batch-create-form";

  const h2 = document.createElement("h2");
  h2.textContent = "New batch";
  form.appendChild(h2);

  const hint = document.createElement("p");
  hint.className = "form-hint";
  hint.textContent =
    "Spine range, diameter, wood, shaft source, purchase date, and comments are " +
    "set on the batch's own page after it's created.";
  form.appendChild(hint);

  function field(labelText, inputEl) {
    const label = document.createElement("label");
    label.appendChild(document.createTextNode(labelText));
    label.appendChild(inputEl);
    form.appendChild(label);
    return inputEl;
  }

  const batchNo = document.createElement("input");
  batchNo.type = "number";
  batchNo.required = true;
  field("Batch #", batchNo);

  const expectedCount = document.createElement("input");
  expectedCount.type = "number";
  expectedCount.min = "1";
  expectedCount.required = true;
  field("Number of shafts", expectedCount);

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Create batch";
  form.appendChild(submit);

  const errorBox = document.createElement("div");
  errorBox.className = "form-error";
  form.appendChild(errorBox);

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errorBox.textContent = "";
    try {
      const batch = await api.post("api/batches", {
        batchNo: Number(batchNo.value),
        expectedCount: Number(expectedCount.value),
      });
      location.hash = `#/batches/${batch.id}`;
    } catch (e) {
      errorBox.textContent = e.message || "Could not create batch";
    }
  });

  return form;
}

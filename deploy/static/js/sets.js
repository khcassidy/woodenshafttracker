// Sets tab: the manual set builder. A set may span batches, but only
// within one (diameter, wood) partition -- confirmed product decision.
// Both sections re-render from the server's response,
// never a client-side patch, matching batches.js and config.js -- and
// each triggers the other's refresh, since building or disbanding a set
// changes what the other section shows.

import { api } from "./api.js";
import { shaftInfoColumns, shaftInfoHeaderCells, shaftInfoRowCells } from "./shaftinfo.js";
import { attachColumnSort } from "./tablesort.js";
import { attachHoverTooltip } from "./tooltip.js";

export async function renderSets(root) {
  const wrap = document.createElement("div");
  wrap.className = "view view-sets";

  const heading = document.createElement("h1");
  heading.textContent = "Sets";
  wrap.appendChild(heading);

  const hint = document.createElement("p");
  hint.className = "form-hint";
  hint.textContent =
    "Build a matched set by hand from the available shafts in one diameter/wood " +
    "partition. A set can draw from more than one batch, but never mixes diameter or wood.";
  wrap.appendChild(hint);

  const builder = await buildBuilderSection(() => list.refresh());
  const list = await buildExistingSetsSection(() => builder.refreshCandidates());

  wrap.appendChild(list.section);
  wrap.appendChild(builder.section);
  root.appendChild(wrap);
}

// ---- builder ----

async function buildBuilderSection(onSetCreated) {
  const section = document.createElement("div");
  section.className = "config-section sets-builder";

  const h2 = document.createElement("h2");
  h2.textContent = "Build a set";
  section.appendChild(h2);

  const [diameters, woods] = await Promise.all([
    api.get("api/lookups/diameter"),
    api.get("api/lookups/wood"),
  ]);

  const pickerRow = document.createElement("div");
  pickerRow.className = "sets-picker-row";

  const diameterSelect = document.createElement("select");
  for (const d of diameters) diameterSelect.appendChild(optionEl(d.id, d.label));
  const woodSelect = document.createElement("select");
  for (const w of woods) woodSelect.appendChild(optionEl(w.id, w.label));

  pickerRow.appendChild(labeledInline("Diameter", diameterSelect));
  pickerRow.appendChild(labeledInline("Wood", woodSelect));
  section.appendChild(pickerRow);

  const table = document.createElement("table");
  table.className = "sets-candidate-table sets-members-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.appendChild(document.createElement("th")); // checkbox column, no header text, not sortable
  const infoHeaderCells = shaftInfoHeaderCells();
  for (const th of infoHeaderCells) headRow.appendChild(th);
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  section.appendChild(table);
  attachHoverTooltip(table, "td.notes-cell", (el) => el.textContent);

  const emptyState = document.createElement("p");
  emptyState.className = "empty-state";
  emptyState.textContent = "No available shafts in this partition.";
  emptyState.hidden = true;
  section.appendChild(emptyState);

  const checkboxes = new Map();
  // Sorting reorders these existing <tr> elements (tbody.appendChild on
  // an attached node moves it) rather than rebuilding cells from
  // scratch, so a checkbox someone already ticked stays ticked.
  let shafts = [];
  const rowsByShaftId = new Map();

  function applySort() {
    for (const s of sorter.sortRows(shafts)) {
      tbody.appendChild(rowsByShaftId.get(s.id));
    }
  }

  const sorter = attachColumnSort(infoHeaderCells, shaftInfoColumns(), applySort);

  async function refreshCandidates() {
    checkboxes.clear();
    rowsByShaftId.clear();
    tbody.innerHTML = "";
    shafts = await api.get(
      `api/partitions/${diameterSelect.value}/${woodSelect.value}/shafts`
    );
    emptyState.hidden = shafts.length > 0;
    for (const s of shafts) {
      const tr = document.createElement("tr");

      const checkTd = document.createElement("td");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkboxes.set(s.id, checkbox);
      checkTd.appendChild(checkbox);
      tr.appendChild(checkTd);

      for (const td of shaftInfoRowCells(s)) tr.appendChild(td);
      rowsByShaftId.set(s.id, tr);
      tbody.appendChild(tr);
    }
    applySort();
  }

  diameterSelect.addEventListener("change", refreshCandidates);
  woodSelect.addEventListener("change", refreshCandidates);
  await refreshCandidates();

  const form = document.createElement("form");
  form.className = "sets-create-form";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "Set name";
  nameInput.required = true;
  form.appendChild(labeledInline("Name", nameInput));

  const targetSizeInput = document.createElement("input");
  targetSizeInput.type = "number";
  targetSizeInput.min = "1";
  targetSizeInput.value = "12";
  form.appendChild(labeledInline("Target size", targetSizeInput));

  const notesInput = document.createElement("textarea");
  notesInput.rows = 2;
  notesInput.placeholder = "Optional comment";
  form.appendChild(labeledInline("Notes", notesInput));

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Build set";
  form.appendChild(submit);

  const errorBox = document.createElement("div");
  errorBox.className = "form-error";
  form.appendChild(errorBox);

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errorBox.textContent = "";
    const shaftIds = [...checkboxes.entries()].filter(([, cb]) => cb.checked).map(([id]) => id);
    if (shaftIds.length === 0) {
      errorBox.textContent = "Select at least one shaft.";
      return;
    }
    try {
      await api.post("api/sets", {
        name: nameInput.value,
        diameterId: Number(diameterSelect.value),
        woodId: Number(woodSelect.value),
        shaftIds,
        targetSize: Number(targetSizeInput.value),
        notes: notesInput.value || null,
      });
      nameInput.value = "";
      notesInput.value = "";
      await refreshCandidates();
      await onSetCreated();
    } catch (e) {
      errorBox.textContent = e.message || "Could not build set";
    }
  });

  section.appendChild(form);
  return { section, refreshCandidates };
}

// ---- existing sets ----

async function buildExistingSetsSection(onSetChanged) {
  const section = document.createElement("div");
  section.className = "config-section sets-list-section";

  const h2 = document.createElement("h2");
  h2.textContent = "Built sets";
  section.appendChild(h2);

  const emptyState = document.createElement("p");
  emptyState.className = "empty-state";
  section.appendChild(emptyState);

  const cardsWrap = document.createElement("div");
  section.appendChild(cardsWrap);

  async function refresh() {
    const sets = await api.get("api/sets");
    emptyState.hidden = sets.length > 0;
    emptyState.textContent = "No sets built yet.";
    cardsWrap.innerHTML = "";
    for (const set of sets) {
      cardsWrap.appendChild(
        buildSetCard(set, {
          onDisband: async () => {
            await api.del(`api/sets/${set.id}`);
            await refresh();
            await onSetChanged();
          },
          onDelete: async () => {
            await api.post(`api/sets/${set.id}:purge`);
            await refresh();
          },
          onNotesSaved: (notes) => api.patch(`api/sets/${set.id}`, { notes }),
          // Adding/removing members changes what's available to build a
          // new set from, but is handled locally within the card (see
          // buildMembersDetails) rather than a full list refresh, so the
          // "Shafts" panel someone has open stays open.
          onMembersChanged: onSetChanged,
        })
      );
    }
  }

  await refresh();
  return { section, refresh };
}

function buildSetCard(set, { onDisband, onDelete, onNotesSaved, onMembersChanged }) {
  const card = document.createElement("div");
  card.className = "sets-card";
  if (set.disbandedAt) card.classList.add("sets-card-disbanded");

  const title = document.createElement("h3");
  function updateTitle() {
    title.textContent = `${set.name} (${set.memberCount}/${set.targetSize})`;
  }
  updateTitle();
  card.appendChild(title);

  const meta = document.createElement("p");
  meta.className = "form-hint";
  meta.textContent = set.disbandedAt
    ? `${set.diameterLabel} / ${set.woodLabel} -- disbanded ${set.disbandedAt}`
    : `${set.diameterLabel} / ${set.woodLabel} -- built ${set.createdAt}`;
  card.appendChild(meta);

  card.appendChild(buildNotesBlock(set, onNotesSaved));
  card.appendChild(
    buildMembersDetails(set, {
      active: !set.disbandedAt,
      onMemberCountChanged: (count) => {
        set.memberCount = count;
        updateTitle();
      },
      onPoolChanged: onMembersChanged,
    })
  );

  if (!set.disbandedAt) {
    const disbandBtn = document.createElement("button");
    disbandBtn.type = "button";
    disbandBtn.className = "sets-card-disband-btn";
    disbandBtn.textContent = "Disband";
    disbandBtn.addEventListener("click", () => {
      if (!confirm(`Disband "${set.name}" and return its shafts to the pool?`)) return;
      onDisband();
    });
    card.appendChild(disbandBtn);
  } else {
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "sets-card-delete-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", () => {
      if (!confirm(`Permanently delete "${set.name}"? This cannot be undone.`)) return;
      onDelete();
    });
    card.appendChild(deleteBtn);
  }

  return card;
}

// A set's comment, shown as plain text with an "Edit notes" toggle that
// swaps in a textarea -- same inline-edit shape as the batch details form
// in entrygrid.js, just smaller since there's only one field.
function buildNotesBlock(set, onNotesSaved) {
  const wrap = document.createElement("div");
  wrap.className = "sets-card-notes";

  const textEl = document.createElement("p");
  textEl.className = "sets-card-notes-text";

  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "sets-card-notes-edit-btn";

  const form = document.createElement("form");
  form.className = "sets-card-notes-form";
  form.hidden = true;

  const textarea = document.createElement("textarea");
  textarea.rows = 2;
  form.appendChild(textarea);

  const formActions = document.createElement("div");
  const saveBtn = document.createElement("button");
  saveBtn.type = "submit";
  saveBtn.textContent = "Save";
  formActions.appendChild(saveBtn);
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.textContent = "Cancel";
  formActions.appendChild(cancelBtn);
  form.appendChild(formActions);

  const errorBox = document.createElement("div");
  errorBox.className = "form-error";
  form.appendChild(errorBox);

  function showText() {
    textEl.textContent = set.notes || "";
    textEl.hidden = !set.notes;
    editBtn.textContent = set.notes ? "Edit notes" : "Add notes";
    editBtn.hidden = false;
    form.hidden = true;
  }
  showText();

  editBtn.addEventListener("click", () => {
    textarea.value = set.notes || "";
    errorBox.textContent = "";
    textEl.hidden = true;
    editBtn.hidden = true;
    form.hidden = false;
    textarea.focus();
  });

  cancelBtn.addEventListener("click", () => showText());

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const notes = textarea.value.trim() || null;
    try {
      await onNotesSaved(notes);
      set.notes = notes;
      showText();
    } catch (e) {
      errorBox.textContent = e.message || "Could not save notes";
    }
  });

  wrap.appendChild(textEl);
  wrap.appendChild(editBtn);
  wrap.appendChild(form);
  return wrap;
}

// The shaft list a set was built from, so "where did that group go" has an
// answer beyond the memberCount in the title. Lazily loaded on first open
// (GET /api/sets -- the list this card came from -- carries no member
// detail) so opening the Sets tab never fires one request per card. For
// an active (not yet disbanded) set, this is also where members are
// added and removed -- reloading just this panel after either action,
// never the whole Built sets list, so the panel stays open.
function buildMembersDetails(set, { active, onMemberCountChanged, onPoolChanged }) {
  const details = document.createElement("details");
  details.className = "sets-card-members";

  const summary = document.createElement("summary");
  function updateSummary() {
    summary.textContent = `Shafts (${set.memberCount})`;
  }
  updateSummary();
  details.appendChild(summary);

  const body = document.createElement("div");
  details.appendChild(body);

  async function reload() {
    try {
      const full = await api.get(`api/sets/${set.id}`);
      onMemberCountChanged(full.memberCount);
      updateSummary();
      renderMembersTable(body, full.members, {
        onRemove: active
          ? async (shaftId) => {
              await api.post(`api/sets/${set.id}/members:remove`, { shaftIds: [shaftId] });
              await onPoolChanged();
              await reload();
            }
          : null,
      });
      if (active) {
        body.appendChild(
          buildAddMembersPicker(set, {
            onAdded: async () => {
              await onPoolChanged();
              await reload();
            },
          })
        );
      }
    } catch (e) {
      body.textContent = e.message || "Could not load shafts";
    }
  }

  let loaded = false;
  details.addEventListener("toggle", async () => {
    if (!details.open || loaded) return;
    loaded = true;
    await reload();
  });

  return details;
}

// The candidate list for adding to an existing set: the same checkbox +
// shaft-info-column + sortable-table shape as the "Build a set" picker in
// buildBuilderSection, just fixed to this set's own partition instead of
// a diameter/wood dropdown pair, since an existing set's partition can't
// change.
function buildAddMembersPicker(set, { onAdded }) {
  const wrap = document.createElement("div");
  wrap.className = "sets-add-members";

  const toggleBtn = document.createElement("button");
  toggleBtn.type = "button";
  toggleBtn.className = "sets-add-members-toggle-btn";
  toggleBtn.textContent = "Add shafts";
  wrap.appendChild(toggleBtn);

  const pickerBox = document.createElement("div");
  pickerBox.hidden = true;
  wrap.appendChild(pickerBox);

  let open = false;

  async function loadPicker() {
    pickerBox.innerHTML = "Loading...";
    let available;
    try {
      available = await api.get(`api/partitions/${set.diameterId}/${set.woodId}/shafts`);
    } catch (e) {
      pickerBox.textContent = e.message || "Could not load available shafts";
      return;
    }
    pickerBox.innerHTML = "";
    if (available.length === 0) {
      const p = document.createElement("p");
      p.className = "empty-state";
      p.textContent = "No available shafts in this partition.";
      pickerBox.appendChild(p);
      return;
    }

    const checkboxes = new Map();
    const table = document.createElement("table");
    table.className = "sets-members-table";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    headRow.appendChild(document.createElement("th")); // checkbox column
    const infoHeaderCells = shaftInfoHeaderCells();
    for (const th of infoHeaderCells) headRow.appendChild(th);
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    const rowsByShaftId = new Map();
    for (const s of available) {
      const tr = document.createElement("tr");
      const checkTd = document.createElement("td");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkboxes.set(s.id, checkbox);
      checkTd.appendChild(checkbox);
      tr.appendChild(checkTd);
      for (const td of shaftInfoRowCells(s)) tr.appendChild(td);
      rowsByShaftId.set(s.id, tr);
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    pickerBox.appendChild(table);
    attachHoverTooltip(table, "td.notes-cell", (el) => el.textContent);
    function applySort() {
      for (const s of sorter.sortRows(available)) tbody.appendChild(rowsByShaftId.get(s.id));
    }
    const sorter = attachColumnSort(infoHeaderCells, shaftInfoColumns(), applySort);
    applySort();

    const errorBox = document.createElement("div");
    errorBox.className = "form-error";

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.textContent = "Add selected";
    addBtn.addEventListener("click", async () => {
      const shaftIds = [...checkboxes.entries()].filter(([, cb]) => cb.checked).map(([id]) => id);
      if (shaftIds.length === 0) {
        errorBox.textContent = "Select at least one shaft.";
        return;
      }
      try {
        await api.post(`api/sets/${set.id}/members:add`, { shaftIds });
        open = false;
        pickerBox.hidden = true;
        toggleBtn.textContent = "Add shafts";
        await onAdded();
      } catch (e) {
        errorBox.textContent = e.message || "Could not add shafts";
      }
    });
    pickerBox.appendChild(addBtn);
    pickerBox.appendChild(errorBox);
  }

  toggleBtn.addEventListener("click", async () => {
    open = !open;
    pickerBox.hidden = !open;
    toggleBtn.textContent = open ? "Cancel" : "Add shafts";
    if (open) await loadPicker();
  });

  return wrap;
}

function renderMembersTable(container, members, { onRemove = null } = {}) {
  container.innerHTML = "";
  if (members.length === 0) {
    const p = document.createElement("p");
    p.className = "empty-state";
    p.textContent = "No shafts currently linked to this set.";
    container.appendChild(p);
    return;
  }
  const table = document.createElement("table");
  table.className = "sets-members-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const headerCells = shaftInfoHeaderCells();
  for (const th of headerCells) headRow.appendChild(th);
  if (onRemove) headRow.appendChild(document.createElement("th")); // remove column
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  container.appendChild(table);
  attachHoverTooltip(table, "td.notes-cell", (el) => el.textContent);

  function renderRows() {
    tbody.innerHTML = "";
    for (const m of sorter.sortRows(members)) {
      const tr = document.createElement("tr");
      for (const td of shaftInfoRowCells(m)) tr.appendChild(td);
      if (onRemove) {
        const actionTd = document.createElement("td");
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "sets-member-remove-btn";
        removeBtn.textContent = "Remove";
        removeBtn.addEventListener("click", () => onRemove(m.id));
        actionTd.appendChild(removeBtn);
        tr.appendChild(actionTd);
      }
      tbody.appendChild(tr);
    }
  }

  const sorter = attachColumnSort(headerCells, shaftInfoColumns(), renderRows);
  renderRows();
}

// ---- shared helpers ----

function optionEl(value, label) {
  const opt = document.createElement("option");
  opt.value = String(value);
  opt.textContent = label;
  return opt;
}

function labeledInline(labelText, inputEl) {
  const label = document.createElement("label");
  label.className = "sets-inline-label";
  label.appendChild(document.createTextNode(labelText));
  label.appendChild(inputEl);
  return label;
}

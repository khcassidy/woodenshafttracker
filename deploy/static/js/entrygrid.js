// The keyboard entry grid: batch rows are pre-created by POST /api/batches,
// so entry here is pure UPDATE -- no row ever appears or shifts under the
// cursor. Enter advances focus *before* the save resolves, so network
// latency never stutters the archer's hands; a save failure flags the row
// instead of moving focus back.

import { ApiError, OfflineError, api, patchShaftField } from "./api.js";
import { loadLookup, optionEl } from "./batches.js";
import { convertWeightLive, deriveWeightDisplay, formatSpineCp, formatSpineMlb } from "./fmt.js";
import { FocusRing, buildRing } from "./focusring.js";
import { loadEntryRules } from "./entryrules.js";
import { buildBatchExportLink } from "./importexport.js";
import { attachHoverTooltip } from "./tooltip.js";

const STRAIGHTNESS_VALUES = ["EXCELLENT", "OK", "BAD", "JUNK"];

export class EntryGrid {
  constructor(root) {
    this.root = root;
    this.batchId = null;
    this.batch = null;
    this.shafts = [];
    this.rules = null;
    this.pass = null;
    this.rowState = new Map(); // seq -> { lastSaved: {...}, errors: Set<field> }
    this.ring = null;
    this.table = null;
    // seq:field -> in-flight commit promise. Enter both commits explicitly
    // AND advances focus, and advancing focus blurs the old cell, which
    // the delegated blur listener also commits -- without this guard, one
    // Enter press fires two concurrent PATCHes for the same field, and the
    // second one loses a UNIQUE-constraint race in shaft_spine_reading.
    this.pending = new Map();
  }

  async mount(batchId) {
    this.batchId = batchId;
    const [batch, rules, diameters, woods, shops, sets] = await Promise.all([
      api.get(`api/batches/${batchId}`),
      loadEntryRules(),
      loadLookup("diameter"),
      loadLookup("wood"),
      loadLookup("shop"),
      api.get("api/sets"),
    ]);
    this.batch = batch;
    this.rules = rules;
    this.diameters = diameters;
    this.woods = woods;
    this.shops = shops;
    // Consumed shafts carry only consumedSetId; look up its name here so
    // buildRow doesn't need a request per row. Fetched once at mount --
    // a set built in another tab mid-session won't retag a row here until
    // the next reload, same as diameters/woods/shops above.
    this.setNames = new Map(sets.map((s) => [s.id, s.name]));

    await this.loadShaftsAndRender();
  }

  // Shared by mount() and by anything that changes the shaft SET itself
  // (insert, delete) rather than one field's value -- those need a fresh
  // row list and a rebuilt ring, since every seq past the change point may
  // have shifted.
  async loadShaftsAndRender() {
    const [shafts, entryState] = await Promise.all([
      api.get(`api/batches/${this.batchId}/shafts`),
      api.get(`api/batches/${this.batchId}/entry-state`),
    ]);
    this.shafts = shafts;
    this.pass = entryState.pass;

    this.rowState = new Map();
    for (const shaft of shafts) {
      const weightDisplay = deriveWeightDisplay(shaft);
      this.rowState.set(shaft.seq, {
        lastSaved: {
          spineA: shaft.spineAText || null,
          spineB: shaft.spineBText || null,
          weightG: weightDisplay.weightG || null,
          weightGr: weightDisplay.weightGr || null,
          straightness: shaft.straightness || null,
          notes: shaft.notes || null,
        },
        // Separate from lastSaved.weightG/weightGr: those two also hold
        // an uncommitted live-preview value (see buildWeightCells), so
        // they cannot answer "has weight actually been saved". This can
        // only change from a real server round-trip (applyServerRow).
        weightDone: shaft.weightCg != null,
        errors: new Set(),
      });
    }

    this.render();
    this.ring = new FocusRing(this.table);
    this.ring.setRing(buildRing(this.shafts, this.batch.entryMode, this.pass));
    this.attachHandlers();

    if (entryState.nextFocus) {
      this.ring.focus(entryState.nextFocus.seq, entryState.nextFocus.field);
    } else {
      this.ring.first();
    }
  }

  destroy() {
    // Listeners are on this.table, which is discarded with the DOM subtree
    // on navigation; nothing else to release. tooltip.js owns one shared
    // tooltip element for the whole page (see app.js's hideTooltip() call
    // on every route change) rather than one per view.
  }

  // ---- rendering ----

  render() {
    this.root.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "view view-entry";

    const back = document.createElement("a");
    back.href = "#/batches";
    back.className = "back-link";
    back.textContent = "← Batches";
    wrap.appendChild(back);

    this.titleEl = document.createElement("h1");
    wrap.appendChild(this.titleEl);
    this.updateTitle();

    wrap.appendChild(this.renderDetailsPanel());
    wrap.appendChild(this.renderControls());
    this.countsEl = document.createElement("div");
    this.countsEl.className = "counts-line";
    wrap.appendChild(this.countsEl);

    const keysHelp = document.createElement("div");
    keysHelp.className = "keys-help";
    keysHelp.textContent =
      "Enter next · Shift+Enter back · \" same as above · = copy A to B · " +
      "Esc undo field · Ctrl+G go to shaft · F8 next problem · F2 toggle mode";
    wrap.appendChild(keysHelp);

    wrap.appendChild(this.renderTable());

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "add-shaft-btn";
    addBtn.textContent = "+ Add shaft";
    addBtn.addEventListener("click", () => this.addShaftAtEnd());
    wrap.appendChild(addBtn);

    this.root.appendChild(wrap);
    this.refreshCounts();
  }

  updateTitle() {
    this.titleEl.textContent = `Batch ${this.batch.batchNo}${
      this.batch.nominalSpineLabel ? " · " + this.batch.nominalSpineLabel : ""
    }`;
  }

  // ---- batch details: batch #, spine label, diameter, wood, shop,
  // purchase date, comments -- all editable after creation. Changing
  // batchNo relabels every shaft server-side (see rename_batch_no);
  // seqWidth alone stays fixed, since it was sized to the shaft count at
  // creation and every label's padding depends on it.

  renderDetailsPanel() {
    const panel = document.createElement("div");
    panel.className = "batch-details";

    this.detailsSummaryEl = document.createElement("div");
    this.detailsSummaryEl.className = "details-summary";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "edit-details-btn";
    editBtn.textContent = "Edit details";

    this.detailsFormEl = this.buildDetailsForm();
    this.detailsFormEl.hidden = true;

    editBtn.addEventListener("click", () => {
      this.populateDetailsForm();
      this.detailsFormEl.hidden = false;
      editBtn.hidden = true;
    });
    this._showEditButton = () => {
      editBtn.hidden = false;
    };

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "delete-batch-btn";
    deleteBtn.textContent = "Delete batch";
    deleteBtn.addEventListener("click", () => this.deleteBatch());

    // detailsSummaryEl must be attached before updateDetailsSummary() runs:
    // it inserts the comments block via detailsSummaryEl.after(...), which
    // is a silent no-op on a node with no parent yet.
    panel.appendChild(this.detailsSummaryEl);
    panel.appendChild(editBtn);
    panel.appendChild(deleteBtn);
    panel.appendChild(buildBatchExportLink(this.batchId));
    panel.appendChild(this.detailsFormEl);
    this.updateDetailsSummary();
    return panel;
  }

  async deleteBatch() {
    const count = this.shafts.length;
    if (
      !window.confirm(
        `Delete batch ${this.batch.batchNo} and all ${count} of its shafts? This cannot be undone.`
      )
    ) {
      return;
    }
    try {
      await api.del(`api/batches/${this.batchId}`);
      location.hash = "#/batches";
    } catch (e) {
      window.alert(e.message || "Could not delete batch");
    }
  }

  updateDetailsSummary() {
    const diameterLabel =
      this.diameters.find((d) => d.id === this.batch.diameterId)?.label || "Unknown";
    const woodLabel = this.woods.find((w) => w.id === this.batch.woodId)?.label || "Unknown";
    const shopLabel = this.shops.find((s) => s.id === this.batch.shopId)?.label || null;
    const parts = [diameterLabel, woodLabel];
    if (shopLabel) parts.push(shopLabel);
    if (this.batch.purchaseDate) parts.push(`purchased ${this.batch.purchaseDate}`);
    this.detailsSummaryEl.textContent = parts.join(" · ");

    if (this._commentsEl) this._commentsEl.remove();
    if (this.batch.description) {
      this._commentsEl = document.createElement("div");
      this._commentsEl.className = "details-comments";
      this._commentsEl.textContent = this.batch.description;
      this.detailsSummaryEl.after(this._commentsEl);
    } else {
      this._commentsEl = null;
    }
  }

  buildDetailsForm() {
    const form = document.createElement("form");
    form.className = "batch-details-form";

    function field(labelText, inputEl, { span2 = false } = {}) {
      const label = document.createElement("label");
      if (span2) label.className = "span-2";
      label.appendChild(document.createTextNode(labelText));
      label.appendChild(inputEl);
      form.appendChild(label);
      return inputEl;
    }

    // Left column
    this.editBatchNo = document.createElement("input");
    this.editBatchNo.type = "number";
    this.editBatchNo.required = true;
    field("Batch #", this.editBatchNo);

    this.editDiameter = document.createElement("select");
    for (const d of this.diameters) this.editDiameter.appendChild(optionEl(d.id, d.label));
    field("Diameter", this.editDiameter);

    this.editShop = document.createElement("select");
    this.editShop.appendChild(optionEl("", "(not recorded)"));
    for (const s of this.shops) this.editShop.appendChild(optionEl(s.id, s.label));
    field("Shaft Source", this.editShop);

    // Right column
    this.editNominalLabel = document.createElement("input");
    this.editNominalLabel.type = "text";
    this.editNominalLabel.placeholder = "e.g. 55-60#";
    field("Spine range label", this.editNominalLabel);

    this.editWood = document.createElement("select");
    for (const w of this.woods) this.editWood.appendChild(optionEl(w.id, w.label));
    field("Wood sort", this.editWood);

    this.editPurchaseDate = document.createElement("input");
    this.editPurchaseDate.type = "date";
    field("Purchase date", this.editPurchaseDate);

    // Full width
    this.editDescription = document.createElement("textarea");
    this.editDescription.rows = 3;
    field("Comments", this.editDescription, { span2: true });

    const actions = document.createElement("div");
    actions.className = "form-actions";

    const saveBtn = document.createElement("button");
    saveBtn.type = "submit";
    saveBtn.textContent = "Save";
    actions.appendChild(saveBtn);

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", () => {
      form.hidden = true;
      this._showEditButton();
    });
    actions.appendChild(cancelBtn);
    form.appendChild(actions);

    this.detailsErrorEl = document.createElement("div");
    this.detailsErrorEl.className = "form-error span-2";
    form.appendChild(this.detailsErrorEl);

    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this.saveDetails();
    });

    return form;
  }

  populateDetailsForm() {
    this.editBatchNo.value = String(this.batch.batchNo);
    this.editNominalLabel.value = this.batch.nominalSpineLabel || "";
    this.editDiameter.value = String(this.batch.diameterId);
    this.editWood.value = String(this.batch.woodId);
    this.editShop.value = this.batch.shopId != null ? String(this.batch.shopId) : "";
    this.editPurchaseDate.value = this.batch.purchaseDate || "";
    this.editDescription.value = this.batch.description || "";
    this.detailsErrorEl.textContent = "";
  }

  async saveDetails() {
    this.detailsErrorEl.textContent = "";
    try {
      const updated = await api.patch(`api/batches/${this.batchId}`, {
        batchNo: Number(this.editBatchNo.value),
        nominalSpineLabel: this.editNominalLabel.value || null,
        diameterId: Number(this.editDiameter.value),
        woodId: Number(this.editWood.value),
        shopId: this.editShop.value ? Number(this.editShop.value) : null,
        purchaseDate: this.editPurchaseDate.value || null,
        description: this.editDescription.value || null,
      });
      this.batch = updated;
      // A batch-number change relabels every shaft server-side (see
      // rename_batch_no); refresh the '#' column to match, without a full
      // reload that would drop in-progress edits and focus.
      this.shafts = await api.get(`api/batches/${this.batchId}/shafts`);
      this.refreshShaftLabels();
      this.updateTitle();
      this.updateDetailsSummary();
      this.detailsFormEl.hidden = true;
      this._showEditButton();
    } catch (e) {
      this.detailsErrorEl.textContent = e.message || "Could not save batch details";
    }
  }

  renderControls() {
    const controls = document.createElement("div");
    controls.className = "entry-controls";

    const modeFieldset = document.createElement("fieldset");
    modeFieldset.className = "mode-toggle";
    const legend = document.createElement("legend");
    legend.textContent = "Entry mode";
    modeFieldset.appendChild(legend);

    for (const [value, text] of [
      ["per_shaft", "Per shaft"],
      ["per_field", "Per field"],
    ]) {
      const label = document.createElement("label");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "entryMode";
      radio.value = value;
      radio.checked = this.batch.entryMode === value;
      radio.addEventListener("change", () => this.setMode(value));
      label.appendChild(radio);
      label.appendChild(document.createTextNode(" " + text));
      modeFieldset.appendChild(label);
    }
    controls.appendChild(modeFieldset);
    this.modeFieldset = modeFieldset;

    this.passButtonsEl = document.createElement("div");
    this.passButtonsEl.className = "pass-buttons";
    for (const [value, text] of [
      ["spine", "Spine"],
      ["weight", "Weight"],
      ["straightness", "Straightness"],
    ]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = text;
      btn.dataset.pass = value;
      btn.addEventListener("click", () => this.setPass(value));
      this.passButtonsEl.appendChild(btn);
    }
    controls.appendChild(this.passButtonsEl);
    this.updatePassButtons();

    return controls;
  }

  updatePassButtons() {
    const showPasses = this.batch.entryMode === "per_field";
    this.passButtonsEl.style.display = showPasses ? "" : "none";
    for (const btn of this.passButtonsEl.children) {
      btn.classList.toggle("active", btn.dataset.pass === this.pass);
    }
  }

  renderTable() {
    const table = document.createElement("table");
    table.className = "entry-grid";
    table.tabIndex = -1;

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    const headers = [
      "#",
      "Spine A",
      "Spine B",
      "Avg",
      "A–B",
      "Weight (g)",
      "Weight (gr)",
      "Str",
      "Notes",
      "Actions",
    ];
    for (const text of headers) {
      const th = document.createElement("th");
      th.textContent = text;
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const shaft of this.shafts) {
      tbody.appendChild(this.buildRow(shaft));
    }
    table.appendChild(tbody);

    this.table = table;
    return table;
  }

  buildRow(shaft) {
    const tr = document.createElement("tr");
    tr.dataset.rowSeq = String(shaft.seq);
    tr.classList.toggle("row-consumed", shaft.consumedSetId != null);

    const labelTd = document.createElement("td");
    labelTd.className = "shaft-label";
    this.renderLabelCell(labelTd, shaft);
    tr.appendChild(labelTd);

    tr.appendChild(this.buildInputCell(shaft.seq, "spineA", shaft.spineAText || ""));
    tr.appendChild(this.buildInputCell(shaft.seq, "spineB", shaft.spineBText || ""));

    const avgTd = document.createElement("td");
    avgTd.className = "readonly avg-cell";
    avgTd.dataset.rowSeq = String(shaft.seq);
    avgTd.dataset.readout = "avg";
    avgTd.textContent = formatSpineMlb(shaft.avgSpineMlb);
    tr.appendChild(avgTd);

    const spreadTd = document.createElement("td");
    spreadTd.className = "readonly spread-cell";
    spreadTd.dataset.rowSeq = String(shaft.seq);
    spreadTd.dataset.readout = "spread";
    spreadTd.textContent = formatSpineCp(shaft.spineSpreadCp);
    tr.appendChild(spreadTd);

    const [weightGTd, weightGrTd] = this.buildWeightCells(shaft);
    tr.appendChild(weightGTd);
    tr.appendChild(weightGrTd);

    tr.appendChild(this.buildStraightnessCell(shaft));
    tr.appendChild(this.buildInputCell(shaft.seq, "notes", shaft.notes || ""));
    tr.appendChild(this.buildActionsCell(shaft));

    return tr;
  }

  // Shared by buildRow and refreshShaftLabels, so a batch-number rename
  // (which only overwrites the label text, not the whole row) keeps the
  // set tag instead of wiping it out. The tag is plain text appended to
  // the label, not a boxed badge -- a bordered inline-block here doesn't
  // respect the cell's narrow auto width and renders on top of neighboring
  // cells instead of wrapping.
  renderLabelCell(labelTd, shaft) {
    labelTd.textContent = shaft.label;
    if (shaft.consumedSetId != null) {
      const setName = this.setNames.get(shaft.consumedSetId) || `Set #${shaft.consumedSetId}`;
      const tag = document.createElement("span");
      tag.className = "shaft-set-tag";
      tag.textContent = ` – ${setName}`;
      labelTd.appendChild(tag);
      labelTd.title = `In set: ${setName}`;
    } else {
      labelTd.title = "";
    }
  }

  buildInputCell(seq, field, value) {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.type = "text";
    if (field !== "notes") input.inputMode = "decimal";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.value = value;
    input.dataset.seq = String(seq);
    input.dataset.field = field;
    td.appendChild(input);
    return td;
  }

  // Two live-linked cells sharing one canonical value: typing in either
  // one immediately recomputes the other's *displayed* text. That preview
  // is not itself a pending edit -- lastSaved is updated to match it too,
  // so tabbing through the untouched sibling commits nothing. Only the
  // field the archer actually typed into gets sent, with its own unit.
  buildWeightCells(shaft) {
    const display = deriveWeightDisplay(shaft);

    const tdG = document.createElement("td");
    const inputG = document.createElement("input");
    inputG.type = "text";
    inputG.inputMode = "decimal";
    inputG.autocomplete = "off";
    inputG.spellcheck = false;
    inputG.value = display.weightG;
    inputG.dataset.seq = String(shaft.seq);
    inputG.dataset.field = "weightG";
    tdG.appendChild(inputG);

    const tdGr = document.createElement("td");
    const inputGr = document.createElement("input");
    inputGr.type = "text";
    inputGr.inputMode = "decimal";
    inputGr.autocomplete = "off";
    inputGr.spellcheck = false;
    inputGr.value = display.weightGr;
    inputGr.dataset.seq = String(shaft.seq);
    inputGr.dataset.field = "weightGr";
    tdGr.appendChild(inputGr);

    inputG.addEventListener("input", () => {
      const converted = convertWeightLive(inputG.value, "g");
      inputGr.value = converted;
      this.rowState.get(shaft.seq).lastSaved.weightGr = converted || null;
    });
    inputGr.addEventListener("input", () => {
      const converted = convertWeightLive(inputGr.value, "gr");
      inputG.value = converted;
      this.rowState.get(shaft.seq).lastSaved.weightG = converted || null;
    });

    return [tdG, tdGr];
  }

  buildActionsCell(shaft) {
    const td = document.createElement("td");
    td.className = "row-actions";

    const insertBtn = document.createElement("button");
    insertBtn.type = "button";
    insertBtn.className = "row-action-btn";
    insertBtn.title = `Insert a new blank shaft after ${shaft.label}`;
    insertBtn.textContent = "+";
    insertBtn.addEventListener("click", () => this.insertShaftAfter(shaft.seq));
    td.appendChild(insertBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "row-action-btn row-action-delete";
    deleteBtn.title = `Delete ${shaft.label}`;
    deleteBtn.textContent = "×";
    deleteBtn.addEventListener("click", () => this.deleteShaft(shaft.seq, shaft.label));
    td.appendChild(deleteBtn);

    return td;
  }

  buildStraightnessCell(shaft) {
    const td = document.createElement("td");
    const select = document.createElement("select");
    select.dataset.seq = String(shaft.seq);
    select.dataset.field = "straightness";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "–";
    select.appendChild(blank);
    for (const value of STRAIGHTNESS_VALUES) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = value.charAt(0) + value.slice(1).toLowerCase();
      select.appendChild(opt);
    }
    select.value = shaft.straightness || "";
    td.appendChild(select);
    return td;
  }

  // ---- keyboard + commit ----

  attachHandlers() {
    this.table.addEventListener("keydown", (ev) => this.onKeydown(ev));
    this.table.addEventListener(
      "blur",
      (ev) => {
        const cell = ev.target.closest("[data-seq]");
        if (!cell) return;
        this.commitField(Number(cell.dataset.seq), cell.dataset.field);
      },
      true
    );
    attachHoverTooltip(this.table, 'input[data-field="notes"]', (el) => el.value);
  }

  onKeydown(ev) {
    const cell = ev.target.closest("[data-seq]");
    if (!cell) return;
    const seq = Number(cell.dataset.seq);
    const field = cell.dataset.field;

    if (ev.key === "Enter" || ev.key === "Tab") {
      ev.preventDefault();
      this.commitField(seq, field);
      this.ring.advance(seq, field, ev.shiftKey ? -1 : 1);
      return;
    }
    if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
      if (cell.tagName === "SELECT") return; // native option-cycling
      ev.preventDefault();
      this.commitField(seq, field);
      this.moveVertical(seq, field, ev.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (ev.key === "Escape") {
      ev.preventDefault();
      this.revertField(seq, field);
      return;
    }
    if (ev.key === '"' && cell.tagName === "INPUT") {
      ev.preventDefault();
      this.copyFromAbove(seq, field);
      return;
    }
    if (ev.key === "=" && field === "spineB") {
      ev.preventDefault();
      this.copySpineAtoB(seq);
      return;
    }
    if (ev.ctrlKey && (ev.key === "g" || ev.key === "G")) {
      ev.preventDefault();
      this.goToShaft();
      return;
    }
    if (ev.key === "F8") {
      ev.preventDefault();
      this.jumpToNextProblem(seq, field);
      return;
    }
    if (ev.key === "F2") {
      ev.preventDefault();
      this.toggleMode();
      return;
    }
  }

  readCellValue(cell) {
    const raw = cell.value.trim();
    return raw === "" ? null : raw;
  }

  // Enter/Tab call this explicitly (needed so the very last cell in the
  // ring, which has nowhere to advance to and so never blurs, still
  // commits); the delegated blur listener also calls this on every focus
  // change. Both paths funnel through the same in-flight guard, so the
  // two calls that a single Enter press produces collapse into one PATCH.
  commitField(seq, field) {
    const key = `${seq}:${field}`;
    const inFlight = this.pending.get(key);
    if (inFlight) return inFlight;

    const cell = this.ring.cellFor(seq, field);
    if (!cell) return Promise.resolve();
    const rowState = this.rowState.get(seq);
    const rawValue = this.readCellValue(cell);
    if (rawValue === rowState.lastSaved[field]) return Promise.resolve(); // nothing changed

    const promise = this._doCommit(seq, field, rawValue, rowState).finally(() => {
      this.pending.delete(key);
    });
    this.pending.set(key, promise);
    return promise;
  }

  async _doCommit(seq, field, rawValue, rowState) {
    this.setCellStatus(seq, field, "saving");
    // The grid's grams/grains columns are two views onto the API's single
    // weight+weightUnit contract -- translate the ring field name to it.
    let fields;
    if (field === "weightG" || field === "weightGr") {
      fields = { weight: rawValue };
      if (rawValue !== null) fields.weightUnit = field === "weightG" ? "g" : "gr";
    } else {
      fields = { [field]: rawValue };
    }

    try {
      const row = await patchShaftField(this.batchId, seq, fields);
      rowState.lastSaved[field] = rawValue;
      rowState.errors.delete(field);
      this.applyServerRow(seq, row);
      const hasWarning = row.warnings && row.warnings.length > 0;
      this.setCellStatus(seq, field, hasWarning ? "warn" : "ok", row.warnings);
    } catch (e) {
      if (e instanceof OfflineError) {
        rowState.lastSaved[field] = rawValue; // optimistic: applies once flushed
        rowState.errors.delete(field);
        this.setCellStatus(seq, field, "queued", [{ message: e.message }]);
      } else if (e instanceof ApiError) {
        rowState.errors.add(field);
        const messages = e.issues && e.issues.length ? e.issues : [{ message: e.message }];
        this.setCellStatus(seq, field, "error", messages);
      } else {
        rowState.errors.add(field);
        this.setCellStatus(seq, field, "error", [{ message: String(e) }]);
      }
    }
    this.refreshCounts();
  }

  applyServerRow(seq, row) {
    const avgTd = this.table.querySelector(`[data-row-seq="${seq}"][data-readout="avg"]`);
    if (avgTd) avgTd.textContent = formatSpineMlb(row.avgSpineMlb);
    const spreadTd = this.table.querySelector(`[data-row-seq="${seq}"][data-readout="spread"]`);
    if (spreadTd) spreadTd.textContent = formatSpineCp(row.spineSpreadCp);

    // Always resync both weight columns from the authoritative response,
    // regardless of which field was just committed: row already carries
    // the full current state, and this is what turns "I just saved
    // grams" into "the grains column now shows the true equivalent".
    const weightGCell = this.ring.cellFor(seq, "weightG");
    const weightGrCell = this.ring.cellFor(seq, "weightGr");
    if (weightGCell && weightGrCell) {
      const rowState = this.rowState.get(seq);
      const display = deriveWeightDisplay(row);
      weightGCell.value = display.weightG;
      weightGrCell.value = display.weightGr;
      rowState.lastSaved.weightG = display.weightG || null;
      rowState.lastSaved.weightGr = display.weightGr || null;
      rowState.weightDone = row.weightCg != null;
    }
  }

  refreshShaftLabels() {
    for (const shaft of this.shafts) {
      const row = this.table.querySelector(`tr[data-row-seq="${shaft.seq}"]`);
      const labelTd = row?.querySelector(".shaft-label");
      if (labelTd) this.renderLabelCell(labelTd, shaft);
    }
  }

  // ---- insert / delete shafts ----

  async insertShaftAfter(seq) {
    try {
      await api.post(`api/batches/${this.batchId}/shafts:insert`, { afterSeq: seq });
      await this.loadShaftsAndRender();
    } catch (e) {
      window.alert(e.message || "Could not insert a shaft");
    }
  }

  addShaftAtEnd() {
    const maxSeq = this.shafts.reduce((max, s) => Math.max(max, s.seq), 0);
    return this.insertShaftAfter(maxSeq);
  }

  async deleteShaft(seq, label) {
    if (!window.confirm(`Delete shaft ${label}? This cannot be undone.`)) return;
    try {
      await api.del(`api/batches/${this.batchId}/shafts/${seq}`);
      await this.loadShaftsAndRender();
    } catch (e) {
      window.alert(e.message || "Could not delete shaft");
    }
  }

  setCellStatus(seq, field, level, messages) {
    const cell = this.ring.cellFor(seq, field);
    if (!cell) return;
    cell.classList.remove("status-ok", "status-warn", "status-error", "status-saving", "status-queued");
    cell.classList.add(`status-${level}`);
    cell.title = messages && messages.length ? messages.map((m) => m.message).join("; ") : "";
  }

  revertField(seq, field) {
    const cell = this.ring.cellFor(seq, field);
    if (!cell) return;
    const rowState = this.rowState.get(seq);
    cell.value = rowState.lastSaved[field] || "";
    // The value is back to whatever was last actually saved, so any
    // error/warning indicator for the in-progress edit no longer applies.
    // "none" rather than "ok": this revert didn't itself save anything.
    rowState.errors.delete(field);
    this.setCellStatus(seq, field, "none", []);
    this.refreshCounts();
    cell.focus();
    if (typeof cell.select === "function") cell.select();
  }

  copyFromAbove(seq, field) {
    const seqs = this.shafts.map((s) => s.seq).sort((a, b) => a - b);
    const idx = seqs.indexOf(seq);
    if (idx <= 0) return;
    const aboveCell = this.ring.cellFor(seqs[idx - 1], field);
    const cell = this.ring.cellFor(seq, field);
    if (!aboveCell || !cell) return;
    cell.value = aboveCell.value;
  }

  copySpineAtoB(seq) {
    const spineA = this.ring.cellFor(seq, "spineA");
    const spineB = this.ring.cellFor(seq, "spineB");
    if (!spineA || !spineB) return;
    spineB.value = spineA.value;
  }

  moveVertical(seq, field, delta) {
    const seqs = this.shafts.map((s) => s.seq).sort((a, b) => a - b);
    const idx = seqs.indexOf(seq);
    const next = idx + delta;
    if (next < 0 || next >= seqs.length) return;
    this.ring.focus(seqs[next], field);
  }

  goToShaft() {
    const answer = window.prompt("Shaft # (e.g. 12):");
    if (!answer) return;
    const seq = Number(answer.trim());
    if (!this.shafts.some((s) => s.seq === seq)) return;
    const ringField = this.ring.ring.find((r) => r.seq === seq);
    if (ringField) this.ring.focus(ringField.seq, ringField.field);
  }

  jumpToNextProblem(fromSeq, fromField) {
    const idx = this.ring.indexOf(fromSeq, fromField);
    const n = this.ring.ring.length;
    for (let step = 1; step <= n; step++) {
      const candidate = this.ring.ring[(idx + step) % n];
      const rowState = this.rowState.get(candidate.seq);
      if (rowState && rowState.errors.has(candidate.field)) {
        this.ring.focus(candidate.seq, candidate.field);
        return;
      }
    }
  }

  async setPass(pass) {
    this.pass = pass;
    this.ring.setRing(buildRing(this.shafts, this.batch.entryMode, pass));
    this.updatePassButtons();
    this.ring.first();
  }

  async toggleMode() {
    const newMode = this.batch.entryMode === "per_shaft" ? "per_field" : "per_shaft";
    const focused = document.activeElement;
    const focusedSeq = focused && focused.dataset.seq ? Number(focused.dataset.seq) : null;

    // F2 doesn't move focus away from the current cell the way Enter does,
    // so nothing would otherwise blur-commit an in-progress edit.
    if (focusedSeq !== null) {
      await this.commitField(focusedSeq, focused.dataset.field);
    }

    const updated = await api.patch(`api/batches/${this.batchId}`, { entryMode: newMode });
    this.batch = updated;
    const entryState = await api.get(`api/batches/${this.batchId}/entry-state`);
    this.pass = entryState.pass;

    this.modeFieldset.querySelectorAll('input[name="entryMode"]').forEach((radio) => {
      radio.checked = radio.value === newMode;
    });
    this.updatePassButtons();
    this.ring.setRing(buildRing(this.shafts, this.batch.entryMode, this.pass));

    if (focusedSeq !== null) {
      const stillPresent = this.ring.ring.find((r) => r.seq === focusedSeq);
      if (stillPresent) {
        this.ring.focus(stillPresent.seq, stillPresent.field);
        return;
      }
    }
    this.ring.first();
  }

  async setMode(newMode) {
    if (newMode === this.batch.entryMode) return;
    await this.toggleMode();
  }

  refreshCounts() {
    let spineA = 0;
    let spineB = 0;
    let weight = 0;
    let straightness = 0;
    let attention = 0;
    for (const [, state] of this.rowState) {
      if (state.lastSaved.spineA !== null) spineA++;
      if (state.lastSaved.spineB !== null) spineB++;
      if (state.weightDone) weight++;
      if (state.lastSaved.straightness !== null) straightness++;
      if (state.errors.size > 0) attention++;
    }
    const total = this.shafts.length;
    let text =
      `${total} shafts · spine A ${spineA}/${total} · spine B ${spineB}/${total} · ` +
      `weight ${weight}/${total} · straightness ${straightness}/${total}`;
    if (attention > 0) text += `      ⚠ ${attention} need attention`;
    this.countsEl.textContent = text;
  }
}

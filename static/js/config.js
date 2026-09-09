// Configuration tab: the ordered lookup lists (diameter, wood, shop) and
// the entry-validation rules. Every list mutation re-renders from the
// server's response rather than re-fetching, since create/rename/toggle/
// reorder each already return the current list or row. Analysis
// parameter sets moved to analysis.js's own "Edit parameters" panel, so
// they can be tweaked and re-run without leaving that page.

import { api } from "./api.js";

const LOOKUP_KINDS = {
  diameter: {
    title: "Diameter options",
    extraFields: [{ key: "sixtyFourths", label: "64ths", type: "number" }],
  },
  wood: { title: "Wood sorts", extraFields: [] },
  shop: {
    title: "Shaft Sources",
    extraFields: [
      { key: "url", label: "URL", type: "text" },
      { key: "notes", label: "Notes", type: "text" },
    ],
  },
};

export async function renderConfig(root) {
  const wrap = document.createElement("div");
  wrap.className = "view view-config";

  const heading = document.createElement("h1");
  heading.textContent = "Configuration";
  wrap.appendChild(heading);

  const hint = document.createElement("p");
  hint.className = "form-hint";
  hint.textContent =
    "Pull-downs elsewhere in the app follow this order, top to bottom -- " +
    "put what you use most at the top with ↑/↓.";
  wrap.appendChild(hint);

  for (const kind of Object.keys(LOOKUP_KINDS)) {
    wrap.appendChild(await buildLookupSection(kind));
  }

  wrap.appendChild(await buildEntryRulesSection());

  root.appendChild(wrap);
}

// ---- ordered lookup lists ----

async function buildLookupSection(kind) {
  const { title, extraFields } = LOOKUP_KINDS[kind];
  const section = document.createElement("div");
  section.className = "config-section";

  const h2 = document.createElement("h2");
  h2.textContent = title;
  section.appendChild(h2);

  const table = document.createElement("table");
  table.className = "config-list";
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  section.appendChild(table);

  const errorBox = document.createElement("div");
  errorBox.className = "form-error";
  section.appendChild(errorBox);

  function renderRows(options) {
    const visible = options.filter((o) => !o.isUnknown);
    tbody.innerHTML = "";
    visible.forEach((option, index) => {
      tbody.appendChild(buildRow(option, index, visible));
    });
  }

  function buildRow(option, index, visible) {
    const tr = document.createElement("tr");

    const moveTd = document.createElement("td");
    const upBtn = document.createElement("button");
    upBtn.type = "button";
    upBtn.textContent = "↑";
    upBtn.disabled = index === 0;
    upBtn.addEventListener("click", () => reorder(visible, index, index - 1));
    const downBtn = document.createElement("button");
    downBtn.type = "button";
    downBtn.textContent = "↓";
    downBtn.disabled = index === visible.length - 1;
    downBtn.addEventListener("click", () => reorder(visible, index, index + 1));
    moveTd.appendChild(upBtn);
    moveTd.appendChild(downBtn);
    tr.appendChild(moveTd);

    const labelInput = document.createElement("input");
    labelInput.type = "text";
    labelInput.value = option.label;
    const labelTd = document.createElement("td");
    labelTd.appendChild(labelInput);
    tr.appendChild(labelTd);

    const extraInputs = {};
    for (const field of extraFields) {
      const input = document.createElement("input");
      input.type = field.type;
      input.value = option[field.key] ?? "";
      extraInputs[field.key] = input;
      const td = document.createElement("td");
      td.appendChild(input);
      tr.appendChild(td);
    }

    const activeTd = document.createElement("td");
    const activeCheckbox = document.createElement("input");
    activeCheckbox.type = "checkbox";
    activeCheckbox.checked = option.isActive;
    activeCheckbox.addEventListener("change", async () => {
      try {
        await api.patch(`api/lookups/${kind}/${option.id}`, { isActive: activeCheckbox.checked });
      } catch (e) {
        errorBox.textContent = e.message || "Could not update";
        activeCheckbox.checked = !activeCheckbox.checked;
      }
    });
    activeTd.appendChild(activeCheckbox);
    tr.appendChild(activeTd);

    const saveTd = document.createElement("td");
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = "Save";
    saveBtn.addEventListener("click", async () => {
      errorBox.textContent = "";
      const body = { label: labelInput.value };
      for (const field of extraFields) {
        const raw = extraInputs[field.key].value;
        body[field.key] = field.type === "number" ? (raw ? Number(raw) : null) : raw || null;
      }
      try {
        await api.patch(`api/lookups/${kind}/${option.id}`, body);
      } catch (e) {
        errorBox.textContent = e.message || "Could not save";
      }
    });
    saveTd.appendChild(saveBtn);
    tr.appendChild(saveTd);

    return tr;
  }

  async function reorder(visible, fromIndex, toIndex) {
    const ids = visible.map((o) => o.id);
    [ids[fromIndex], ids[toIndex]] = [ids[toIndex], ids[fromIndex]];
    errorBox.textContent = "";
    try {
      const updated = await api.put(`api/lookups/${kind}/order`, { ids });
      renderRows(updated);
    } catch (e) {
      errorBox.textContent = e.message || "Could not reorder";
    }
  }

  const initial = await api.get(`api/lookups/${kind}`);
  renderRows(initial);

  section.appendChild(buildAddForm(kind, extraFields, errorBox, renderRows));
  return section;
}

function buildAddForm(kind, extraFields, errorBox, renderRows) {
  const form = document.createElement("form");
  form.className = "config-add-form";

  const labelInput = document.createElement("input");
  labelInput.type = "text";
  labelInput.placeholder = "New label";
  labelInput.required = true;
  form.appendChild(labelInput);

  const extraInputs = {};
  for (const field of extraFields) {
    const input = document.createElement("input");
    input.type = field.type;
    input.placeholder = field.label;
    extraInputs[field.key] = input;
    form.appendChild(input);
  }

  const addBtn = document.createElement("button");
  addBtn.type = "submit";
  addBtn.textContent = "Add";
  form.appendChild(addBtn);

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errorBox.textContent = "";
    const body = { label: labelInput.value };
    for (const field of extraFields) {
      const raw = extraInputs[field.key].value;
      body[field.key] = field.type === "number" ? (raw ? Number(raw) : null) : raw || null;
    }
    try {
      await api.post(`api/lookups/${kind}`, body);
      const updated = await api.get(`api/lookups/${kind}`);
      renderRows(updated);
      form.reset();
    } catch (e) {
      errorBox.textContent = e.message || "Could not add";
    }
  });

  return form;
}

// ---- entry validation rules ----

async function buildEntryRulesSection() {
  const section = document.createElement("div");
  section.className = "config-section";
  const h2 = document.createElement("h2");
  h2.textContent = "Entry validation rules";
  section.appendChild(h2);

  const hint = document.createElement("p");
  hint.className = "form-hint";
  hint.textContent =
    "The bands the entry grid uses for step warnings and plausible-range checks.";
  section.appendChild(hint);

  const rules = await api.get("api/config/entry-rules");

  const form = document.createElement("form");
  form.className = "config-params-form";

  function field(labelText, inputEl) {
    const label = document.createElement("label");
    label.appendChild(document.createTextNode(labelText));
    label.appendChild(inputEl);
    form.appendChild(label);
    return inputEl;
  }

  const spineStep = numberInput(rules.spineStepCp / 100);
  field("Spine step (lb)", spineStep);
  const weightStep = numberInput(rules.weightStepCg / 100);
  field("Weight step (g)", weightStep);

  const spineHardMin = numberInput(rules.spineHardMinCp / 100);
  field("Spine hard minimum (lb)", spineHardMin);
  const spineHardMax = numberInput(rules.spineHardMaxCp / 100);
  field("Spine hard maximum (lb)", spineHardMax);
  const spineWarnMin = numberInput(rules.spineWarnMinCp / 100);
  field("Spine warn below (lb)", spineWarnMin);
  const spineWarnMax = numberInput(rules.spineWarnMaxCp / 100);
  field("Spine warn above (lb)", spineWarnMax);

  const weightHardMin = numberInput(rules.weightHardMinCg / 100);
  field("Weight hard minimum (g)", weightHardMin);
  const weightHardMax = numberInput(rules.weightHardMaxCg / 100);
  field("Weight hard maximum (g)", weightHardMax);
  const weightWarnMin = numberInput(rules.weightWarnMinCg / 100);
  field("Weight warn below (g)", weightWarnMin);
  const weightWarnMax = numberInput(rules.weightWarnMaxCg / 100);
  field("Weight warn above (g)", weightWarnMax);

  const batchOutlierSpine = numberInput(rules.batchOutlierSpineCp / 100);
  field("Batch outlier: spine distance from median (lb)", batchOutlierSpine);
  const batchOutlierWeight = numberInput(rules.batchOutlierWeightCg / 100);
  field("Batch outlier: weight distance from median (g)", batchOutlierWeight);

  const grainsPerGram = document.createElement("input");
  grainsPerGram.type = "text";
  grainsPerGram.value = rules.grainsPerGram;
  field("Grains per gram", grainsPerGram);

  const saveBtn = document.createElement("button");
  saveBtn.type = "submit";
  saveBtn.textContent = "Save";
  form.appendChild(saveBtn);

  const errorBox = document.createElement("div");
  errorBox.className = "form-error";
  form.appendChild(errorBox);

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errorBox.textContent = "";
    try {
      await api.patch("api/config/entry-rules", {
        spineStepCp: Math.round(Number(spineStep.value) * 100),
        weightStepCg: Math.round(Number(weightStep.value) * 100),
        spineHardMinCp: Math.round(Number(spineHardMin.value) * 100),
        spineHardMaxCp: Math.round(Number(spineHardMax.value) * 100),
        spineWarnMinCp: Math.round(Number(spineWarnMin.value) * 100),
        spineWarnMaxCp: Math.round(Number(spineWarnMax.value) * 100),
        weightHardMinCg: Math.round(Number(weightHardMin.value) * 100),
        weightHardMaxCg: Math.round(Number(weightHardMax.value) * 100),
        weightWarnMinCg: Math.round(Number(weightWarnMin.value) * 100),
        weightWarnMaxCg: Math.round(Number(weightWarnMax.value) * 100),
        batchOutlierSpineCp: Math.round(Number(batchOutlierSpine.value) * 100),
        batchOutlierWeightCg: Math.round(Number(batchOutlierWeight.value) * 100),
        grainsPerGram: grainsPerGram.value,
      });
    } catch (e) {
      errorBox.textContent = e.message || "Could not save";
    }
  });

  section.appendChild(form);
  return section;
}

function numberInput(value) {
  const input = document.createElement("input");
  input.type = "number";
  input.step = "any";
  input.value = value;
  return input;
}

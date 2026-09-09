// Analysis tab: runs the grouping engine (GET /api/analysis) over one
// diameter/wood partition and shows the resulting groups. Each group's
// "Build this set" button hands its member ids straight to POST
// /api/sets -- the exact same call sets.js's own builder makes -- so a
// committed group is a real, consumed set immediately. Committing bumps
// pool_version, so the result just shown is stale by definition; the
// view re-runs itself right after a successful commit rather than
// leaving a picture of the pool that no longer matches the database.

import { api } from "./api.js";
import { formatSpineMlb, formatWeightCg } from "./fmt.js";
import { shaftInfoColumns, shaftInfoHeaderCells, shaftInfoRowCells } from "./shaftinfo.js";
import { attachColumnSort } from "./tablesort.js";
import { attachHoverTooltip } from "./tooltip.js";

export async function renderAnalysis(root) {
  const wrap = document.createElement("div");
  wrap.className = "view view-analysis";

  const heading = document.createElement("h1");
  heading.textContent = "Analysis";
  wrap.appendChild(heading);

  const hint = document.createElement("p");
  hint.className = "form-hint";
  hint.textContent =
    "Runs the selected parameter set's objective over one diameter/wood partition's " +
    "available shafts. \"Build this set\" commits a group exactly as the Sets tab would.";
  wrap.appendChild(hint);

  const [diameters, woods, paramSetsInitial] = await Promise.all([
    api.get("api/lookups/diameter"),
    api.get("api/lookups/wood"),
    api.get("api/params"),
  ]);
  // Reassigned whenever the params editor below saves, creates, or
  // defaults a param set, so runAnalysis() and the picker always see the
  // current set without a round trip back to the server.
  let paramSets = paramSetsInitial;

  const pickerRow = document.createElement("div");
  pickerRow.className = "sets-picker-row";

  const diameterSelect = document.createElement("select");
  for (const d of diameters) diameterSelect.appendChild(optionEl(d.id, d.label));
  const woodSelect = document.createElement("select");
  for (const w of woods) woodSelect.appendChild(optionEl(w.id, w.label));

  const paramSetSelect = document.createElement("select");
  populateParamSetOptions();

  const poolFilterSelect = document.createElement("select");
  poolFilterSelect.appendChild(optionEl("all", "All available"));
  poolFilterSelect.appendChild(optionEl("in_spec", "In-spec only"));

  pickerRow.appendChild(labeledInline("Diameter", diameterSelect));
  pickerRow.appendChild(labeledInline("Wood", woodSelect));
  pickerRow.appendChild(labeledInline("Parameter set", paramSetSelect));
  pickerRow.appendChild(labeledInline("Pool", poolFilterSelect));
  wrap.appendChild(pickerRow);

  wrap.appendChild(buildParamsEditor());

  const runBtn = document.createElement("button");
  runBtn.type = "button";
  runBtn.className = "analysis-run-btn";
  runBtn.textContent = "Run analysis";
  wrap.appendChild(runBtn);

  const errorBox = document.createElement("div");
  errorBox.className = "form-error";
  wrap.appendChild(errorBox);

  const resultsWrap = document.createElement("div");
  resultsWrap.className = "analysis-results";
  wrap.appendChild(resultsWrap);

  async function runAnalysis() {
    errorBox.textContent = "";
    const paramSet = paramSets.find((p) => String(p.id) === paramSetSelect.value);
    try {
      const body = await api.get(
        `api/analysis?diameterId=${diameterSelect.value}&woodId=${woodSelect.value}` +
          `&paramSetId=${paramSetSelect.value}&poolFilter=${poolFilterSelect.value}`
      );
      renderResults(body, paramSet);
    } catch (e) {
      resultsWrap.innerHTML = "";
      errorBox.textContent = e.message || "Could not run analysis";
    }
  }

  function renderResults(body, paramSet) {
    resultsWrap.innerHTML = "";

    const summary = document.createElement("p");
    summary.className = "form-hint";
    const objectiveLabel = body.objective === "MAX_DOZENS" ? "most complete dozens" : "all matched sets";
    const leftoverCount = body.groups.filter((g) => !g.isDozen).length;
    const breakdown =
      body.objective === "MAX_DOZENS" && leftoverCount > 0
        ? ` (${body.groups.length - leftoverCount} dozen, ${leftoverCount} leftover match${
            leftoverCount === 1 ? "" : "es"
          })`
        : "";
    summary.textContent =
      `Objective: ${objectiveLabel}. ${body.candidateCount} candidate shaft` +
      `${body.candidateCount === 1 ? "" : "s"} in this pool. ${body.groups.length} group` +
      `${body.groups.length === 1 ? "" : "s"} found${breakdown} (status: ${body.status}).`;
    resultsWrap.appendChild(summary);

    if (body.groups.length === 0) {
      const emptyState = document.createElement("p");
      emptyState.className = "empty-state";
      emptyState.textContent = "No group satisfies these tolerances in this pool.";
      resultsWrap.appendChild(emptyState);
    }

    for (const group of body.groups) {
      resultsWrap.appendChild(buildGroupCard(group, body, paramSet));
    }

    if (body.unusedShafts.length > 0) {
      const unused = document.createElement("p");
      unused.className = "form-hint";
      unused.textContent = `${body.unusedShafts.length} shaft(s) left over, unused by any group.`;
      resultsWrap.appendChild(unused);
    }
  }

  function buildGroupCard(group, body, paramSet) {
    const card = document.createElement("div");
    card.className = "analysis-group-card";
    if (!group.isDozen) card.classList.add("analysis-group-card-leftover");

    const title = document.createElement("h3");
    if (body.objective === "MAX_DOZENS" && !group.isDozen) {
      // Not a full dozen -- (size/dozenSize) here would read as a dozen
      // that came up short, when this is really a separate, smaller
      // match salvaged from shafts the dozens pass couldn't use.
      title.textContent = `Group ${group.index + 1} (${group.size} shafts -- leftover match, not a dozen)`;
    } else {
      const targetSize = body.dozenSize || group.size;
      title.textContent = `Group ${group.index + 1} (${group.size}/${targetSize})`;
    }
    card.appendChild(title);

    // Two lines, not one dense run-on: "Spine 54.000-57.000 lb" is a
    // range across members, not an average, and calling it "Avg spine"
    // read as if it were one. Range, spread (the actual delta this
    // group's box constraint is checked against), and the true mean are
    // three different numbers -- all three, spelled out, for both axes.
    // Same two lines also go into the build form's Notes below, via
    // spineWeightSummaryLines, so the figures shown here are still on
    // record once the group is gone and only the built set remains.
    const { spine: spineText, weight: weightText } = spineWeightSummaryLines(group);
    const spineLine = document.createElement("p");
    spineLine.className = "form-hint";
    spineLine.textContent = spineText;
    card.appendChild(spineLine);

    const weightLine = document.createElement("p");
    weightLine.className = "form-hint";
    weightLine.textContent = weightText;
    card.appendChild(weightLine);

    const table = document.createElement("table");
    table.className = "sets-members-table";
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    const headerCells = shaftInfoHeaderCells();
    for (const th of headerCells) headRow.appendChild(th);
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);
    card.appendChild(table);

    function renderMemberRows() {
      tbody.innerHTML = "";
      for (const m of memberSorter.sortRows(group.members)) {
        const tr = document.createElement("tr");
        for (const td of shaftInfoRowCells(m)) tr.appendChild(td);
        tbody.appendChild(tr);
      }
    }

    const memberSorter = attachColumnSort(headerCells, shaftInfoColumns(), renderMemberRows);
    renderMemberRows();
    attachHoverTooltip(table, "td.notes-cell", (el) => el.textContent);

    const buildForm = document.createElement("form");
    buildForm.className = "sets-create-form";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.placeholder = "Set name";
    nameInput.required = true;
    buildForm.appendChild(labeledInline("Name", nameInput));

    const notesInput = document.createElement("textarea");
    notesInput.rows = 2;
    notesInput.value = analysisParamsNote(paramSet, body, group);
    buildForm.appendChild(labeledInline("Notes", notesInput));

    const buildBtn = document.createElement("button");
    buildBtn.type = "submit";
    buildBtn.textContent = "Build this set";
    buildForm.appendChild(buildBtn);
    const buildError = document.createElement("div");
    buildError.className = "form-error";
    buildForm.appendChild(buildError);

    buildForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      buildError.textContent = "";
      try {
        await api.post("api/sets", {
          name: nameInput.value,
          diameterId: Number(diameterSelect.value),
          woodId: Number(woodSelect.value),
          shaftIds: group.members.map((m) => m.id),
          targetSize: group.isDozen ? body.dozenSize : group.size,
          notes: notesInput.value || null,
        });
        await runAnalysis();
      } catch (e) {
        buildError.textContent = e.message || "Could not build set";
      }
    });
    card.appendChild(buildForm);

    return card;
  }

  // Keeps paramSetSelect's own option list (labels, "(default)" suffix,
  // newly-created entries) in sync with the paramSets array, which the
  // params editor below reassigns on every save -- without re-fetching,
  // matching batches.js/config.js's "re-render from the response" rule.
  function populateParamSetOptions() {
    const prevValue = paramSetSelect.value;
    paramSetSelect.innerHTML = "";
    for (const p of paramSets) {
      paramSetSelect.appendChild(optionEl(p.id, p.isDefault ? `${p.name} (default)` : p.name));
    }
    const stillExists = paramSets.some((p) => String(p.id) === prevValue);
    const fallback = paramSets.find((p) => p.isDefault) || paramSets[0];
    paramSetSelect.value = stillExists ? prevValue : String(fallback?.id);
  }

  // The full param_set editor, formerly Configuration's own section --
  // moved here so a tolerance can be tweaked and re-run without leaving
  // the page. Always edits whichever set paramSetSelect has selected,
  // rather than a second picker of its own.
  function buildParamsEditor() {
    const details = document.createElement("details");
    details.className = "analysis-params-editor";
    const summary = document.createElement("summary");
    summary.textContent = "Edit parameters";
    details.appendChild(summary);

    const form = document.createElement("form");
    form.className = "config-params-form";

    function field(labelText, inputEl) {
      const label = document.createElement("label");
      label.appendChild(document.createTextNode(labelText));
      label.appendChild(inputEl);
      form.appendChild(label);
      return inputEl;
    }

    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.required = true;
    field("Name", nameInput);

    const spineTol = numberInput(0);
    field("Max spine spread in a group (lb)", spineTol);

    const weightTol = numberInput(0);
    field("Max weight spread in a group (g)", weightTol);

    const objectiveInput = document.createElement("select");
    for (const [value, text] of [
      ["MAX_SET", "All matched sets"],
      ["MAX_DOZENS", "Most complete dozens"],
    ]) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = text;
      objectiveInput.appendChild(opt);
    }
    field("Grouping objective", objectiveInput);

    const dozenSizeInput = numberInput(0);
    field("Dozen size", dozenSizeInput);

    const specMin = numberInput(0);
    field("Spine spec floor (lb)", specMin);

    const specMax = numberInput(0);
    field("Spine spec ceiling (lb)", specMax);

    const abTol = numberInput(0);
    field("Max A–B spine difference (lb)", abTol);

    const minGroupSizeInput = numberInput(0);
    field("Usable group threshold (shafts)", minGroupSizeInput);

    const actions = document.createElement("div");
    actions.className = "config-params-actions";

    const saveBtn = document.createElement("button");
    saveBtn.type = "submit";
    saveBtn.textContent = "Save";
    actions.appendChild(saveBtn);

    const saveAsBtn = document.createElement("button");
    saveAsBtn.type = "button";
    saveAsBtn.textContent = "Save as new";
    actions.appendChild(saveAsBtn);

    const defaultBtn = document.createElement("button");
    defaultBtn.type = "button";
    defaultBtn.className = "make-default-btn";
    actions.appendChild(defaultBtn);

    form.appendChild(actions);

    const errorBox = document.createElement("div");
    errorBox.className = "form-error";
    form.appendChild(errorBox);

    function selected() {
      return paramSets.find((p) => String(p.id) === paramSetSelect.value);
    }

    function populateForm() {
      const current = selected();
      if (!current) return;
      nameInput.value = current.name;
      spineTol.value = current.spineTolMlb / 1000;
      weightTol.value = current.weightTolCg / 100;
      objectiveInput.value = current.objective;
      dozenSizeInput.value = current.dozenSize;
      specMin.value = current.specMinMlb / 1000;
      specMax.value = current.specMaxMlb / 1000;
      abTol.value = current.abTolCp / 100;
      minGroupSizeInput.value = current.minGroupSize;
      errorBox.textContent = "";
      defaultBtn.textContent = current.isDefault ? "Default set" : "Make default";
      defaultBtn.disabled = current.isDefault;
    }

    function fieldsFromForm() {
      return {
        spineTolMlb: Math.round(Number(spineTol.value) * 1000),
        weightTolCg: Math.round(Number(weightTol.value) * 100),
        objective: objectiveInput.value,
        dozenSize: Number(dozenSizeInput.value),
        specMinMlb: Math.round(Number(specMin.value) * 1000),
        specMaxMlb: Math.round(Number(specMax.value) * 1000),
        abTolCp: Math.round(Number(abTol.value) * 100),
        minGroupSize: Number(minGroupSizeInput.value),
      };
    }

    populateForm();
    paramSetSelect.addEventListener("change", populateForm);

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      errorBox.textContent = "";
      const current = selected();
      try {
        const updated = await api.patch(`api/params/${current.id}`, {
          name: nameInput.value,
          ...fieldsFromForm(),
        });
        paramSets = paramSets.map((p) => (p.id === updated.id ? updated : p));
        populateParamSetOptions();
        paramSetSelect.value = String(updated.id);
        populateForm();
        await runAnalysis();
      } catch (e) {
        errorBox.textContent = e.message || "Could not save";
      }
    });

    saveAsBtn.addEventListener("click", async () => {
      errorBox.textContent = "";
      const current = selected();
      if (!nameInput.value || nameInput.value === current.name) {
        errorBox.textContent = "Give the new set a different name first.";
        return;
      }
      try {
        const created = await api.post("api/params", {
          name: nameInput.value,
          ...fieldsFromForm(),
        });
        paramSets = [...paramSets, created];
        populateParamSetOptions();
        paramSetSelect.value = String(created.id);
        populateForm();
        await runAnalysis();
      } catch (e) {
        errorBox.textContent = e.message || "Could not save as a new set";
      }
    });

    defaultBtn.addEventListener("click", async () => {
      errorBox.textContent = "";
      const current = selected();
      try {
        await api.post(`api/params/${current.id}:makeDefault`);
        paramSets = await api.get("api/params");
        populateParamSetOptions();
        paramSetSelect.value = String(current.id);
        populateForm();
      } catch (e) {
        errorBox.textContent = e.message || "Could not set as default";
      }
    });

    details.appendChild(form);
    return details;
  }

  runBtn.addEventListener("click", runAnalysis);
  diameterSelect.addEventListener("change", runAnalysis);
  woodSelect.addEventListener("change", runAnalysis);
  paramSetSelect.addEventListener("change", runAnalysis);
  poolFilterSelect.addEventListener("change", runAnalysis);

  root.appendChild(wrap);
  await runAnalysis();
}

function numberInput(value) {
  const input = document.createElement("input");
  input.type = "number";
  input.step = "any";
  input.value = value;
  return input;
}

// Shared by the group card's own display and analysisParamsNote below,
// so the two never drift into showing different numbers for the same
// group.
function spineWeightSummaryLines(group) {
  const spine =
    `Spine: ${formatSpineMlb(group.avgSpineMinMlb)}-${formatSpineMlb(group.avgSpineMaxMlb)} lb, ` +
    `Average: ${formatSpineMlb(group.avgSpineMeanMlb)} lb, ` +
    `Spread: ${formatSpineMlb(group.avgSpineMaxMlb - group.avgSpineMinMlb)} lb`;
  const weight =
    `Weight: ${formatWeightCg(group.weightMinCg)}-${formatWeightCg(group.weightMaxCg)} g, ` +
    `Average: ${formatWeightCg(group.weightMeanCg)} g, ` +
    `Spread: ${formatWeightCg(group.weightMaxCg - group.weightMinCg)} g`;
  return { spine, weight };
}

// A committed set has no lasting link to the param_set that produced it
// (see app/api/sets.py's _shape_member for why abConsistent/inSpec check
// against whatever the *current* default is, not this one) -- so this is
// the one place the actual numbers used to build it get written down,
// as an editable starting point for the set's own notes rather than
// something recomputed later.
function analysisParamsNote(paramSet, body, group) {
  const objectiveLabel = body.objective === "MAX_DOZENS" ? "most complete dozens" : "all matched sets";
  const poolLabel = body.poolFilter === "in_spec" ? "in-spec only" : "all available";
  const parts = [
    `Built from Analysis: parameter set "${paramSet.name}"`,
    `objective ${objectiveLabel}`,
  ];
  if (body.objective === "MAX_DOZENS") {
    parts.push(`dozen size ${paramSet.dozenSize}`);
    if (!group.isDozen) {
      parts.push(
        `leftover match, not a full dozen (usable group threshold ${paramSet.minGroupSize} shafts)`
      );
    }
  }
  parts.push(`max spine spread ${(paramSet.spineTolMlb / 1000).toFixed(3)} lb`);
  parts.push(`max weight spread ${(paramSet.weightTolCg / 100).toFixed(2)} g`);
  parts.push(`pool ${poolLabel}`);

  const { spine, weight } = spineWeightSummaryLines(group);
  return `${parts.join(", ")}.\n${spine}\n${weight}`;
}

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

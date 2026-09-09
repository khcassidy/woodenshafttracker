// One column definition for every table that lists individual shafts with
// their full measured detail: the Sets tab's candidate picker and its
// built-set member list, and the Analysis tab's group tables. A column
// added here is added everywhere at once, instead of drifting between
// three hand-copied column lists. Each column also carries a `sortValue`
// -- the raw comparable value, not the formatted display string -- so
// tablesort.js's shared click-to-sort can order rows numerically instead
// of alphabetizing "9.00" ahead of "10.00".

import {
  deriveWeightDisplay,
  formatFlag,
  formatSpineCp,
  formatSpineMlb,
  formatStraightness,
} from "./fmt.js";

// true/false/null -> a 3-way ordering (worse, better, unknown) instead of
// comparing "OK"/"off"/"-" as text, which would sort neither sensibly nor
// consistently with what the flag actually means.
function flagSortValue(value) {
  if (value === null || value === undefined) return -1;
  return value ? 1 : 0;
}

const COLUMNS = [
  // seq, not label: label is text ("19-100" < "19-20" as a string) and
  // batchNo,seq is the only order that's actually meaningful across
  // batches -- see core/labels.py.
  { header: "#", get: (s) => s.label, sortValue: (s) => [s.batchNo, s.seq] },
  { header: "Spine A", get: (s) => s.spineAText || "", sortValue: (s) => s.spineACp, num: true },
  { header: "Spine B", get: (s) => s.spineBText || "", sortValue: (s) => s.spineBCp, num: true },
  {
    header: "Avg",
    get: (s) => formatSpineMlb(s.avgSpineMlb),
    sortValue: (s) => s.avgSpineMlb,
    num: true,
  },
  {
    header: "A-B",
    get: (s) => formatSpineCp(s.spineSpreadCp),
    sortValue: (s) => s.spineSpreadCp,
    num: true,
  },
  {
    header: "Weight (g)",
    get: (s) => deriveWeightDisplay(s).weightG,
    sortValue: (s) => s.weightCg,
    num: true,
  },
  {
    header: "Weight (gr)",
    get: (s) => deriveWeightDisplay(s).weightGr,
    sortValue: (s) => s.weightCg,
    num: true,
  },
  {
    header: "Str",
    get: (s) => formatStraightness(s.straightness),
    sortValue: (s) => s.straightness || "",
  },
  { header: "Notes", get: (s) => s.notes || "", sortValue: (s) => s.notes || "", notes: true },
  {
    header: "A-B OK",
    get: (s) => formatFlag(s.abConsistent, "OK", "off"),
    sortValue: (s) => flagSortValue(s.abConsistent),
  },
  {
    header: "In spec",
    get: (s) => formatFlag(s.inSpec, "yes", "no"),
    sortValue: (s) => flagSortValue(s.inSpec),
  },
];

export function shaftInfoColumns() {
  return COLUMNS;
}

export function shaftInfoHeaderCells() {
  return COLUMNS.map((col) => {
    const th = document.createElement("th");
    th.textContent = col.header;
    if (col.num) th.classList.add("num-cell");
    if (col.notes) th.classList.add("notes-cell");
    return th;
  });
}

export function shaftInfoRowCells(shaft) {
  return COLUMNS.map((col) => {
    const td = document.createElement("td");
    td.textContent = col.get(shaft);
    if (col.num) td.classList.add("num-cell");
    if (col.notes) td.classList.add("notes-cell");
    return td;
  });
}

// Click-to-sort table headers, shared by every sortable table in the app
// (previously reimplemented per table -- this generalizes batches.js's
// original inline version). Owns sort state and the header's own click
// handling and ^/v indicator; the caller owns turning a sorted array back
// into DOM, since that differs per table (some can just clear and rebuild
// rows, others -- like a checkbox column -- need to reorder existing row
// elements instead, so checked state isn't lost on every sort).

function compareValues(a, b) {
  // Array-valued sortValue (e.g. [batchNo, seq]) compares element-wise,
  // falling through to the next element only on a tie.
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const cmp = compareValues(a[i], b[i]);
      if (cmp !== 0) return cmp;
    }
    return 0;
  }
  const aMissing = a === null || a === undefined;
  const bMissing = b === null || b === undefined;
  if (aMissing || bMissing) return (aMissing ? 0 : 1) - (bMissing ? 0 : 1);
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

// headerCells: the <th> elements, in column order, already in the DOM.
// columns: parallel array of { sortValue(item) }. defaultIndex: column
// sorted by before any click. Returns { sortRows(items) }, which the
// caller calls after every click (via onChange) and on first render.
export function attachColumnSort(headerCells, columns, onChange, defaultIndex = 0) {
  let sortIndex = defaultIndex;
  let sortAsc = true;

  function updateIndicators() {
    headerCells.forEach((th, i) => {
      th.classList.add("sortable");
      th.classList.toggle("sorted-asc", i === sortIndex && sortAsc);
      th.classList.toggle("sorted-desc", i === sortIndex && !sortAsc);
    });
  }

  headerCells.forEach((th, i) => {
    if (!columns[i]?.sortValue) return; // e.g. a candidate table's leading checkbox column
    th.addEventListener("click", () => {
      if (sortIndex === i) {
        sortAsc = !sortAsc;
      } else {
        sortIndex = i;
        sortAsc = true;
      }
      updateIndicators();
      onChange();
    });
  });

  function sortRows(items) {
    const column = columns[sortIndex];
    return [...items].sort((a, b) => {
      const cmp = compareValues(column.sortValue(a), column.sortValue(b));
      return sortAsc ? cmp : -cmp;
    });
  }

  updateIndicators();
  return { sortRows };
}

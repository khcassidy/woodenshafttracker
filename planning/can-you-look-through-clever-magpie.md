# Wooden Shaft Tracker — Slice 1 Plan

## Context

`d:\dev\shafttracker` holds no code. It holds two planning files: `planning\Wooden Shaft
Tracker Selector.docx` and `planning\Arrow Batch 19 20 20260901.xlsx`. The `.docx` states
the aims. The workbook carries a written calculation spec plus 100 real shafts across
batches 19 and 20.

The workbook already works, so the problem is not a missing calculation. The problem is
that a spreadsheet cannot loop, cannot backtrack, and cannot support fast keyboard entry
at the bench. The spec says so itself, and it names two defects that it cannot fix in
cell formulas. The goal is a local web tool that fixes both and keeps the data.

Two design passes ran against the workbook itself. They confirmed the spec's numbers and
found four errors in it. Section "Corrections to the spec" lists them. Those corrections
are the reason this plan exists in its present shape.

Slice 1 builds the data entry flow only. Slice 2 adds the analysis engine.

## Working boundary

**Read and write only under `d:\dev\shafttracker`.** Other projects on this machine are
out of scope. An earlier design agent broke this rule and read files in a sibling project.
Its conclusions that rested on those files are dropped from this plan.

Two actions follow from this:

1. Write the boundary rule into `CLAUDE.md`, so a future instance inherits it.
2. State the boundary in every subagent prompt.

## Confirmed decisions

| Decision | Choice |
|---|---|
| Storage | Local server plus SQLite |
| Language | Python |
| Grouping objective | Both selectable: biggest matched set, most complete dozens |
| Set composition | One diameter and one wood sort per set; batches may mix |
| In-spec handling | A pool filter, not a third objective |
| Spine floor | `specMin` stays 54.0 lb, one pound below the advertised 55 |
| Network | Bind `0.0.0.0`, no login |
| First slice | Data entry flow |

The network choice carries a stated risk. Anyone on the home network can edit or delete
data. `scripts\backup.py` is the only safety net, so the plan schedules it in slice 1.

## Stack

**Backend: FastAPI plus uvicorn.** Three reasons, each specific to this project:

1. Pydantic validates the decimal-string contract and returns per-field 422 errors. The
   entry grid renders those inline. A hand-rolled `http.server` needs its own validation
   layer to match.
2. `/docs` gives slice 2 a written interface at no cost.
3. `TestClient` runs API tests with no server, so they stay as fast as unit tests.

**Every endpoint function is `def`, never `async def`.** `sqlite3` blocks. A `def`
endpoint runs in a threadpool and cannot stall the event loop. This is a written rule.

**Frontend: static HTML plus vanilla ES modules.** No build step and no template engine.
The entry grid needs imperative focus control across roughly 150 inputs, and the traversal
order changes with a radio button. Focus must advance before each save resolves, so
network delay never breaks the archer's rhythm.

A framework does not help here. HTMX actively fights it, because each fragment swap
destroys focus. The focus ring is about 40 lines of code that we control outright.

**`requirements.txt`** — `fastapi`, `uvicorn`, `watchfiles`, `python-multipart`. The
standard library covers the rest: `sqlite3`, `decimal`, `csv`, `json`, `zipfile`,
`xml.etree`. `openpyxl` is optional and serves XLSX export only. `ortools` belongs to
slice 2.

## Commands

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python run.py --reload          # prints the LAN URL, e.g. http://192.168.1.42:8765

pytest                                     # all tests
pytest tests\test_units.py                 # one file
pytest tests\test_units.py::test_avg_spine_mlb_is_exact_at_quarter_pound
pytest -k avg_spine_mlb                    # by keyword

python scripts\import_workbook.py "planning\Arrow Batch 19 20 20260901.xlsx"
python scripts\backup.py
```

The workbook importer runs a dry run by default. `--commit` is required to write.

Connection settings, per request: `foreign_keys=ON`, `journal_mode=WAL`,
`busy_timeout=5000`, `synchronous=NORMAL`, `sqlite3.Row` as the row factory. One uvicorn
worker only.

## The integer contract

This is the load-bearing rule. **Never store or compare a float for spine or weight.**

```
spineA_cp, spineB_cp : INTEGER  centipounds  = round(lb * 100)     # 0.25 lb -> 25
weight_cg            : INTEGER  centigrams   = round(g  * 100)
avg_spine_mlb        : INTEGER  millipounds  = spine_sum_cp * 5    # exact, no division
spine_spread_cp      : INTEGER  = spine_max_cp - spine_min_cp
```

The `* 5` matters. `(54.25 + 54.50) / 2 = 54.375` needs 1/8 lb resolution. In centipounds
`(5425 + 5450) / 2 = 5437.5`, which is not an integer. Millipounds by `* 5` stays exact.

The general n-reading form is `(spine_sum_cp * 20 + spine_count) // (2 * spine_count)`.
At `spine_count == 2` it is provably identical to `spine_sum_cp * 5`. So `core/derive.py`
implements the general form, and the database asserts the two-reading identity.

**Ingest rule:** parse the decimal *string*. Never `float(x) * 100`. Use `Decimal` with
`ROUND_HALF_UP`, and reject more than 2 decimal places. Keep the entered text for audit.

Python rounds half to even by default, so `round(2.5) == 2`. Pass `ROUND_HALF_UP`
explicitly at every quantisation. A single omission adds a directional bias that no
aggregate test catches.

The workbook proves the value of this. `ANALYSIS!G14` shows `23.648400000000006`. Under
minor units it is exactly `118242 cg / 50`. `CLUSTERS!H9` shows `0.4599999999999973`,
which is exactly `46 cg`.

## Schema

The single source of truth is `app\db\migrations\0001_initial.sql`, applied by
`app\db\migrate.py` through `PRAGMA user_version`. There is no separate `schema.sql` to
drift. Tests call `migrate(conn)`.

### Tables

| Table | Purpose |
|---|---|
| `app_meta` | Holds `pool_version`, bumped by trigger only |
| `diameter_option`, `wood_option`, `shop` | Ordered lookup lists |
| `batch` | One physical purchase |
| `shaft` | The core record, one row per shaft |
| `shaft_spine_reading` | One row per spine reading, ordinal 1..n |
| `param_set` | Named analysis presets |
| `entry_rule` | Validation bands, a singleton row |
| `arrow_set` | A built set |
| `import_run` | Staged imports, so a preview survives a restart |

### Four schema decisions that carry the design

**1. Unknown is a sentinel row, not `NULL`.** `NULL != NULL` in SQL, so `GROUP BY
diameter_id, wood_id` would not group unknowns together. A `NULL` partition cannot be
indexed as a value or named in a URL. So `diameter_option` and `wood_option` each get a
reserved row with `id = 0` and `is_unknown = 1`, and `shaft.diameter_id` and
`shaft.wood_id` are `NOT NULL DEFAULT 0`. Unknown then *is* a partition, with one
`GROUP BY`, one index, and no `COALESCE` anywhere.

This matters because the 100 seed shafts carry no diameter and no wood sort.

`straightness` stays genuinely nullable, because `NULL` means "not yet assessed" and it
is never a partition key.

**2. Spine readings live in a child table from day one.** `SPEC!A54` asks for three or
more readings per shaft. The general average formula degenerates exactly to the frozen
two-reading rule, so the table costs nothing now. Slice 1 restricts its UI and API to
ordinals 1 and 2. A third reading later becomes a UI change plus one relaxed `CHECK`,
with no data migration.

A view keeps the entry grid and the export as a plain `SELECT`:

```sql
CREATE VIEW shaft_entry_v AS ...   -- pivots ordinals 1 and 2 to spine_a_cp / spine_b_cp
```

**3. The exactness rule is a database constraint.** No code path, importer, or migration
can bypass it:

```sql
CHECK (spine_count <> 2 OR avg_spine_mlb = spine_sum_cp * 5)
```

**4. Never sort a pull-down alphabetically.** Each lookup table has an explicit
`sort_order` column, and it is not unique. One endpoint reorders a list:
`PUT /api/lookups/{kind}/order {ids:[...]}` rewrites `sort_order = 1..n` in one
transaction. The Unknown sentinels sit at `sort_order = 999`, so they render last.

### Stored against derived

**Stored:** `shaft_spine_reading.{ordinal, value_cp, entered_text}`,
`shaft.{weight_cg, weight_text, weight_unit, straightness, diameter_id, wood_id, seq,
consumed_set_id}`, and all of `batch`, the lookups, `param_set`, `entry_rule`,
`arrow_set`.

**Materialised derived**, written by `core/derive.py` in the same transaction as the
reading it depends on: `shaft.{spine_count, spine_sum_cp, spine_min_cp, spine_max_cp,
avg_spine_mlb, spine_spread_cp}` and `shaft.label`. These are the hot analysis columns.
Slice 2 must fetch one partition with a single index scan and no arithmetic.

**Derived on read, never stored:** `inSpec`, `abConsistent`, the grams-to-grains display,
every decimal rendering, all summary means, and the histogram bins. `inSpec` and
`abConsistent` depend on editable parameters. If materialised, a parameter edit becomes an
O(n) rewrite, and a stale flag can leak into an export. The workbook agrees, because
`ANALYSIS!H31` and `I31` are formulas over `$B$5`, `$B$6` and `$B$7`.

### The covering index slice 2 reads

```sql
CREATE INDEX ix_shaft_analysis
  ON shaft(diameter_id, wood_id, avg_spine_mlb, weight_cg, id)
  WHERE consumed_set_id IS NULL
    AND avg_spine_mlb IS NOT NULL
    AND weight_cg     IS NOT NULL
    AND (straightness IS NULL OR straightness <> 'JUNK');
```

## The keyboard entry flow

Files: `static\js\focusring.js`, `entrygrid.js`, `grain.js`, `api.js`.

**Rows are pre-created.** `POST /api/batches` inserts `expectedCount` blank shaft rows in
the same transaction as the batch. Entry then becomes pure `UPDATE`. There are no inserts,
no id round trip, and no rows that shift under the cursor. "Partly measured" becomes the
natural resting state instead of a special case.

**Both entry modes are one data-driven ring.** This is the whole mechanism:

```js
function buildRing(rows, mode, pass) {
  if (mode === 'per_shaft')
    return rows.flatMap(r => [[r.seq,'spineA'], [r.seq,'spineB'], [r.seq,'weight']]);
  if (pass === 'spine')
    return rows.flatMap(r => [[r.seq,'spineA'], [r.seq,'spineB']]);
  if (pass === 'weight')
    return rows.map(r => [r.seq,'weight']);
  return rows.map(r => [r.seq,'straightness']);
}
```

Mode 2's second pass is a different ring over the same DOM. A mode switch rebuilds the
ring only. It triggers no re-render, no refetch, and no data loss.

**Keys.** `Enter` and `Tab` commit and advance. `Tab` is overridden to follow the ring,
not DOM order. `Shift+Enter` steps back, which is the main correction path. `Esc` reverts
one field. `"` copies the cell above. `=` copies spine A into spine B. `Ctrl+G` jumps to a
shaft number. `F8` jumps to the next flagged row. `F2` toggles the mode.

`=` earns its key: 76 of the 100 seed shafts have spine B equal to spine A. `Enter` on an
empty B is deliberately *not* overloaded, because a blank B is a legal state.

**Focus advances first, then the save fires.** The reverse order would make every keystroke
wait on the network. One `PATCH` per committed field goes through a pending queue. A
failure never moves focus backwards; it flags the row instead. Failed writes mirror to
`localStorage` and flush through a bulk endpoint on reconnect. A garage with weak wifi must
not cost 40 shafts of work. There is no global Save button.

**Resume is computed server-side.** `GET /api/batches/{id}/entry-state` returns the mode,
the pass, the per-field counts, and `nextFocus`. `batch.entry_mode` and `batch.entry_pass`
persist in the database, so a tablet at the bench reopens in the same place as the laptop.
`localStorage` is a cache, not the truth.

**Validation runs in five ordered checks**, from `core/validate.py`, mirrored to the client
from `GET /api/config/entry-rules`:

1. Shape — reject anything but `^-?\d+(\.\d{1,2})?$`. Accept a leading `.` and a comma
   decimal separator, because an EU numpad emits a comma.
2. Hard band — reject out of range. This catches `560` typed for `56`.
3. Grain — warn when the value is not a multiple of 0.5 lb. Amber, non-blocking.
4. Warn band — warn on an unusual value.
5. Batch outlier — once the batch holds 5 readings, warn beyond 10 lb or 3 g from the
   batch median.

Check 5 is the one that catches `566` typed for `56`, which every range check passes.
Errors block the save. Warnings do not. Neither blocks focus.

**Use `<input type="text" inputmode="decimal">`, never `type="number"`.** Spinners
intercept the arrow keys that the ring binds. Worse, `type="number"` sets `.value` to `""`
on invalid content, which destroys the exact text we must retain. Always call `select()`
on focus, or a refocus and retype turns `23.23` into `23.2356`.

## Import and export

- CSV is the interchange format, with header aliases, a BOM, and CRLF.
- JSON is the full-fidelity backup.
- XLSX read uses `zipfile` plus `ElementTree`, and reads the `<v>` element as text. It
  never touches a float.
- Import is two-phase. A preview stages into `import_run` and reports what it will do. The
  preview is where the tool prompts for the missing diameter and wood sort.
- `scripts\import_workbook.py` is the one-off for the 100 seed shafts.

Grains entry is the one lossy path in the system. 350 gr becomes 22.6791… g, stores as
`2268` cg, and reads back as 349.9998 gr. So store `weight_cg` as canonical, keep
`weight_text` and `weight_unit`, and show the converted grams at entry time. Store the
constant as the text `'15.4324'` and parse it with `Decimal`.

**The API requires decimal values as JSON strings and rejects numbers with 422.**
`{"weight": 23.230}` arrives as the float `23.23`, so the trailing zero is gone before any
validator runs. That would make the audit requirement unsatisfiable.

## What slice 1 must deliver for slice 2

Slice 2 drops `core/grouping.py` in and imports nothing new. Slice 1 owes it four things:

1. `GET /api/partitions`, returning `{diameter, wood, available, consumed, junk,
   unmeasured, total}`. The brief's three counts do not reconcile during Mode 2 pass 1,
   when 50 shafts hold spine values and no weight. So `available` means analysable, and
   `unmeasured` is explicit.
2. `POST /api/sets` as a manual set builder, with an idempotency key, a mixed-partition
   guard, and 409 on a member consumed since the analysis ran. Built in slice 1, this
   de-risks slice 2's concurrency contract against real data.
3. `pool_version`, bumped by trigger on every shaft and reading change. Application code
   never bumps it, because a forgotten bump serves a stale analysis. It is opaque and
   monotonic; a 100-shaft import bumps it about 300 times, so it is not a change count.
4. A split cache key. `groupingKey` covers `poolVersion`, the partition, `spine_tol_mlb`,
   `weight_tol_cg`, `objective` and `dozen_size`. `presentationKey` covers
   `spec_min_mlb`, `spec_max_mlb`, `ab_tol_cp` and `min_group_size`. The spec is explicit
   that the second group are flags only. A single combined key would throw away a valid
   solve when `specMin` moves from 54 to 54.5.

The in-spec pool filter is a `PoolFilter` field, so it composes with both objectives. The
UI must show the dozen count both with and without it, because on the real data the filter
changes the answer.

## Corrections to the planning spec

Both agents verified these against the workbook.

**1. The spec's dozens fix does nothing.** `SPEC!B298` proposes a score of
`floor(size/12)` first and raw size second. That ordering is strictly monotonic in size, so
its argmax equals plain largest-count. Shipping it would give the largest-set objective
under a different label. The real defect is at partition level, and no window score can fix
a partition-level defect.

**2. Greedy loses half the dozens on the real data.** Greedy largest-first finds 1 dozen.
Exact set-packing finds 2, in 28 ms. An independent max-flow check confirmed 2 and proved 3
impossible. So greedy must not be the default for the dozens objective. Slice 2 needs a
solver, which is the reason this plan chose Python.

**3. The parameter units are ambiguous, and the natural reading is wrong by ten.** The
spec gives `specMin` 54.0, `specMax` 60.0 and `spineTol` 3.0 with no unit suffix, beside a
table that establishes centipounds. All three compare against `avg_spine_mlb`, which is
millipounds. Store `spine_tol_mlb = 3000`, `spec_min_mlb = 54000`, `spec_max_mlb = 60000`.
`ab_tol_cp = 100` genuinely is centipounds, because it compares against
`spine_spread_cp`. Every column name carries its unit suffix, and the two units never meet
in one expression.

**4. `BATCH#-SHAFT#` has two defects.** `19-100` does not fit a 2-digit pad. Worse,
`'19-100' < '19-20'` as text, so any list sorted by label is silently mis-ordered — which
breaks the stated "sort by shaft number" requirement. Fix: store `batch_no` and `seq` as
integers, materialise `label` from `core/labels.py`, add `batch.seq_width` fixed at batch
creation, and **sort by `seq`, never by `label`**.

Two smaller items: the spec's exact O(n³) search is correct but needlessly cubic, and a
sweep line returns the identical answer far faster; and the histogram uses half-open bins
while grouping uses closed bounds, which is deliberate and must stay, with a comment so
nobody "fixes" it.

## File layout

```
d:\dev\shafttracker\
  CLAUDE.md  README.md  pyproject.toml  requirements.txt  run.py
  shafttracker.db                 # gitignored; the one file to back up
  core/                           # PURE. stdlib and decimal only. No DB, no HTTP.
    units.py  labels.py  derive.py  validate.py  types.py
    grouping.py                   # slice 2 lands here; not created now
  app/
    main.py  settings.py  deps.py
    db/  connection.py  migrate.py  migrations\0001_initial.sql  repo_*.py
    api/ errors.py  schemas.py  batches.py  shafts.py  lookups.py
         params.py  partitions.py  sets.py  importexport.py
    io/  csv_io.py  json_io.py  xlsx_read.py  xlsx_write.py
  static/
    index.html  css\app.css
    js\ api.js  focusring.js  entrygrid.js  batches.js  shaftlist.js
        config.js  grain.js  fmt.js
  scripts/  import_workbook.py  backup.py
  tests/    conftest.py  test_*.py  fixtures\batch19_20.csv
  planning/                       # unchanged
```

`core/` is the load-bearing boundary. It imports the standard library only.
`app/db/repo_shafts.py` calls `core.derive` and writes the result. `tests/test_core_purity.py`
enforces the boundary mechanically.

## Build order

1. `core/units.py`, `labels.py`, `derive.py`, plus their tests and `test_core_purity.py`.
   The integer contract is proved before anything depends on it.
2. `0001_initial.sql`, `migrate.py`, `connection.py`, plus `test_schema.py`.
3. `app/io/xlsx_read.py`, `scripts/import_workbook.py`, `test_import_workbook.py`. Real
   data lands in the database on day one. Everything after this is built on real shafts.
4. Repos, `schemas.py`, `errors.py`, then lookups, params, batches, shafts, partitions.
5. `static/` — `api.js`, `fmt.js`, `grain.js`, `focusring.js`, `entrygrid.js`. The grid is
   built against 50 already-populated real rows.
6. CSV and JSON import/export, plus `test_export_roundtrip.py`.
7. `sets.py`, the manual set builder with both 409 paths.
8. `config.js`, `backup.py`, and a rewrite of `CLAUDE.md` with the real commands and the
   working boundary rule.

## Verification

**The golden suite comes from the workbook, and it must go green at step 3.** Every figure
below was verified against `ANALYSIS`, so each one is a frozen assertion:

- 100 shafts, 50 per batch, labels `19-01`…`19-50` and `20-01`…`20-50`.
- `avg_spine_mlb` in `[54000, 60000]`: 37 in batch 19, 38 in batch 20, **75** combined.
- Below floor: 13, 12, **25**. Above ceiling: **0**.
- Mean avg spine, combined: `5522000 mlb / 100`, so exactly 55.220 lb.
- Weight sums: 118242, 117925, 236167 cg. Ranges 2118–2676 and 2146–2609 cg.
- `spine_spread_cp > 100` on exactly one shaft: `20-50`, at 2.0 lb.
- All 200 spine readings are exact multiples of 50 cp. No weight exceeds 2 decimal places.

**Unit tests.** Boundary cases at `.005` for `ROUND_HALF_UP`. The quarter-pound case
`54.25 + 54.50` must give `avg_spine_mlb = 54375`. A three-reading case must give 55417
mlb, to prove the general formula. Reject 3 decimal places. Reject a JSON number where a
string is required.

**Schema tests.** Assert that the `avg_spine_mlb = spine_sum_cp * 5` `CHECK` rejects a bad
write. Assert that `pool_version` moves on an insert, an update, and a delete.

**API tests** run through `TestClient`. Cover: `PATCH` with an omitted field against an
explicit `null`; the entry-state resume for both modes and both Mode 2 passes; a 409 from
`POST /api/sets` when a member is already consumed; a rejected mixed-partition set.

**End to end, by hand.** Run these steps in order:

1. `python scripts\import_workbook.py "planning\Arrow Batch 19 20 20260901.xlsx" --commit
   --diameter '11/32"' --wood 'Northern Pine'`
2. `python run.py --reload`, then open the printed LAN URL.
3. Confirm the batch list shows batches 19 and 20 with 50 shafts each.
4. Create a new batch of 12. Enter it in Mode 1 with the keyboard only, and touch no mouse.
5. Create a second batch of 12. Enter spine in Mode 2 pass 1. Close the tab. Reopen it, and
   confirm the cursor lands on shaft 1's weight field.
6. Type `566` into a spine field. Confirm the batch-outlier warning appears.
7. Reorder the wood sort list, and confirm the batch form's pull-down follows that order.
8. Export all data to CSV, then reimport it into an empty database. Confirm every
   `weight_text` and every `avg_spine_mlb` matches.
9. `GET /api/partitions` and confirm `available + consumed + junk + unmeasured == total`.
10. `python scripts\backup.py`, then confirm the backup file opens.

Step 8 is the one that catches a float leak, because a round trip through the export is
where a lost trailing zero shows up.

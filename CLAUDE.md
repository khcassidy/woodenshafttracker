# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local web tool for tracking wooden arrow shafts: batches purchased,
each shaft's spine and weight, and grouping shafts into matched sets —
by hand (the Sets tab) or automatically (the Analysis tab's grouping
engine). It replaces a hand-built spreadsheet — `planning/Arrow Batch 19
20 20260901.xlsx` — whose `SPEC` tab was the calculation reference for
the analysis engine. `planning/Wooden Shaft Tracker Selector.docx`
states the original aims.

Stack: FastAPI + SQLite on the backend, static HTML/CSS and hand-written
vanilla-JS ES modules on the frontend — no build step, no frontend
framework. Chosen because the grouping objective ("most complete
dozens") needs a real solver, and Python has one (OR-Tools' CP-SAT) where
Node does not; see the `## Design decisions` section below.

## Commands

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python run.py --reload            # dev server, prints the LAN URL

pytest                                            # all tests
pytest tests\test_units.py                        # one file
pytest tests\test_schema.py::test_avg_spine_mlb_check_rejects_wrong_value   # one test
pytest -k avg_spine_mlb                            # by keyword

python scripts\import_workbook.py "planning\Arrow Batch 19 20 20260901.xlsx"
python scripts\import_workbook.py "planning\Arrow Batch 19 20 20260901.xlsx" `
    --commit --diameter '11/32"' --wood 'Northern Pine'

python scripts\backup.py          # copies shafttracker.db -> backups\shafttracker-<UTC ts>.db
```

The workbook importer defaults to a dry run; `--commit` is required to
write. `scripts/backup.py` uses SQLite's own `Connection.backup()` API, so
it's safe to run while the server is live — never copy the `.db` file
directly, since a raw copy of a WAL-mode database mid-write can be torn.

## Working boundary

**Read and write only inside this project directory.** Never read or cite
another project on this machine as precedent — an earlier design pass did
this and its conclusions had to be discarded. State this boundary
explicitly in any subagent prompt you write.

**Never delete `shafttracker.db` without asking first.** It is the user's
real data, not test scaffolding. Use `scripts/backup.py` before any
operation that touches it, and prefer a separate `SHAFTTRACKER_DB=verify.db`
instance on another port for your own manual/Playwright verification —
never experiment against the user's live database or its running server.

**`uvicorn --reload` is not reliable in this environment.** It has been
observed to fire once and then silently stop watching for further changes,
leaving a stale process serving old routes with no error. After a backend
change, prefer stopping and restarting the dev server outright, and
confirm new routes actually registered (e.g. `curl .../openapi.json`)
rather than trusting the reload log.

## Architecture

### The `core/` boundary

`core/` must touch no DB, no HTTP, no web framework — not literally
"standard library only": `core/grouping.py` imports `ortools`, a genuine
third-party solver, and that's fine. `tests/test_core_purity.py` enforces
an explicit denylist (`sqlite3`, `fastapi`, `starlette`, `uvicorn`,
`pydantic`, `http`, `socket`, `requests`, `urllib`), not an allowlist —
`ortools` was never on it, because the boundary's actual purpose is
"pure, testable without a database, provably deterministic," not
"stdlib-only" for its own sake.

- `core/units.py` — every Decimal ↔ integer-minor-unit conversion. The
  single most load-bearing file in the project (see below). `mean_minor`
  is the one place an *average of already-minor-unit values* is taken
  (e.g. a group's mean spine across its members) — `sum(values) /
  len(values)` on plain ints is a float in Python 3, so it goes through
  Decimal + ROUND_HALF_UP like every other conversion here, never a bare
  `/`.
- `core/labels.py` — `BATCH#-SHAFT#` label formatting. Sorts must use
  `seq`, never the label string (`"19-100" < "19-20"` as text).
- `core/derive.py` — `avg_spine_mlb` and friends from a list of spine
  readings. The n-reading formula is provably identical to the frozen
  2-reading rule at `count == 2`; see the comment there before touching it.
- `core/validate.py` — step/hard-band/warn-band checks against the
  `entry_rule` bands. Returns `ValidationIssue`s; only a `blocking` one
  raises `ValidationBlocked`.
- `core/grouping.py` — the analysis engine's CP-SAT solver. One modeling
  technique for both grouping objectives: assign shafts to a small number
  of (avg spine, weight) box-constrained "slots," via reified `OnlyEnforceIf`
  constraints (no big-M). `solve_max_set` is the K=1, no-fixed-size case;
  `solve_max_dozens` is the K=n⌊/dozen_size⌋, each-active-slot-exactly-
  `dozen_size` case. It knows nothing about `spec_min/max_mlb` or
  `ab_tol_cp` — those are presentation-only and applied afterward in
  `app/db/repo_analysis.py`, so a future result cache could key the solve
  separately from those purely cosmetic parameters.

### Integer minor units — never a float for spine or weight

Spine is stored as **centipounds** (`spine_a_cp`, 1 lb = 100), weight as
**centigrams** (`weight_cg`, 1 g = 100), and the derived two-reading
average spine as **millipounds** (`avg_spine_mlb`). The two-reading
identity `avg_spine_mlb == spine_sum_cp * 5` is enforced by a `CHECK`
constraint in the schema itself, not just in application code.

Ingest a decimal value from its **string**, via `Decimal` with
`ROUND_HALF_UP` (`core/units.py`) — never `float(x) * 100`. The API layer
backs this: `ShaftPatchRequest`'s decimal fields are `StrictStr`, so a bare
JSON number (which would silently drop a typed trailing zero) is rejected
with a 422 before it reaches parsing.

The client mirrors this discipline loosely for live UI feedback only
(`static/js/fmt.js`'s `convertWeightLive`, `static/js/entryrules.js`) —
those use plain JS floats, which is fine, because nothing computed there
is ever sent back to the server as authoritative; the server always
re-parses the raw text the archer actually typed.

### Database (`app/db/migrations/*.sql`)

Single source of truth, applied via `PRAGMA user_version`
(`app/db/migrate.py`) — no separate `schema.sql` to drift. `0001_initial.sql`
is the original schema; later `NNNN_*.sql` files are additive migrations
(e.g. `0002_rename_entry_rule_step.sql` renamed `entry_rule`'s
`*_grain_*` columns to `*_step_*`, since "grain" collided with "grains"
as the archery weight unit already used elsewhere). Never edit an
already-applied migration's SQL in place — the live database has already
run it and recorded that in its own `user_version`, so an in-place edit
only changes what a *future* fresh database would see, silently
diverging from what's actually live. Always add a new migration file
instead, even for a rename.

- **Unknown is a sentinel row (`id = 0`, `is_unknown = 1`), never `NULL`.**
  `diameter_id`/`wood_id` are `NOT NULL DEFAULT 0` so an unassigned value
  is still a real, groupable partition key — `NULL != NULL` in SQL would
  break `GROUP BY` and URL addressing.
- **`shaft_spine_reading` is a child table**, not fixed A/B columns, so a
  future third reading needs no migration. Slice 1's UI only uses
  ordinals 1–2; `shaft_entry_v` pivots them back to `spine_a_cp`/`spine_b_cp`
  for the entry grid and exports.
- **`pool_version` bumps only via trigger**, never application code, so a
  forgotten bump can never silently serve a stale analysis. It's opaque
  and monotonic — a 100-shaft import bumps it ~300 times.
- **Lookup lists sort by an explicit, non-unique `sort_order`**, never
  alphabetically — reordering rewrites `1..n` in one transaction
  (`PUT /api/lookups/{kind}/order`). This is a stated product requirement,
  not an implementation detail.
- Materialized-vs-derived-on-read split: `avg_spine_mlb` etc. are
  materialized, so the analysis engine's candidate query
  (`repo_shafts.list_partition_shafts`) is one index scan over
  `ix_shaft_analysis`, no arithmetic; `inSpec`/`abConsistent` are computed
  on read because they depend on editable `param_set` values.

### API (`app/api/`, `app/db/repo_*.py`)

One router file per resource area, each backed by a `repo_*.py` with the
actual SQL. `app/api/errors.py` centralizes exception → HTTP mapping,
including a generic `sqlite3.IntegrityError` → 409 handler (parses the
`UNIQUE constraint failed: table.column` message), so a route doesn't need
its own try/except for a duplicate `batch_no` or lookup label.

PATCH endpoints use `body.model_dump(exclude_unset=True)` throughout to
distinguish "field omitted" from "field explicitly set to `null`" (clears
it) — see `app/api/shafts.py::patch_shaft` or `app/api/batches.py::patch_batch`
for the pattern.

Insert/delete of a shaft (`app/db/repo_batches.py::insert_shaft`/
`delete_shaft`) renumber every shaft after the change point — insert
processes highest-`seq`-first, delete processes lowest-`seq`-first, so no
`(batch_id, seq)` or label ever collides mid-transaction.

Import (`app/db/repo_import.py`) stages into `import_run` for preview,
then commits separately — nothing is written to `shaft`/`batch` until an
explicit second call. CSV and JSON each adapt their own shape into one
canonical staged-row dict (`csv_io.to_staged_rows`/`json_io.to_staged_rows`)
before `stage_rows` ever sees them, so the validation/commit path only
has to know one row shape. Import only ever *creates* batches whose
`batch_no` doesn't already exist — never merges into or overwrites one.

`GET /api/partitions/{diameter_id}/{wood_id}/shafts` (`repo_shafts.list_partition_shafts`)
is the one candidate-shaft query shared by the manual set builder and the
analysis engine — never duplicated between them. `POST /api/sets`
(`repo_sets.create_set`) is the *only* way a shaft ever gets consumed: it
takes an explicit `shaftIds` list, so both a person checking boxes on the
Sets tab and `GET /api/analysis`'s "Build this set" button call the exact
same endpoint. It enforces the single-partition rule (every member must
share the set's diameter and wood) and re-checks each shaft is still
unconsumed in the same transaction as the consuming `UPDATE`, raising
`SetMembersConsumedError` (→ 409) on a lost race rather than silently
double-using a shaft. `DELETE /api/sets/{id}` disbands a set, returning
every member to the pool (`consumed_set_id`/`consumed_at` cleared).

`GET /api/analysis` (`repo_analysis.run_analysis`) runs `core/grouping.py`
over one partition's available shafts, per the selected `param_set`'s
`objective`. The in-spec pool filter (`?poolFilter=in_spec`) is a
request-time toggle, not a saved `param_set` field — it reuses the
existing `spec_min/max_mlb` columns as bounds and composes with either
objective, matching the confirmed product decision that in-spec is a
*filter*, not a third objective. There is deliberately no persistent
result cache: solves run in tens of milliseconds at realistic partition
sizes (the workbook's own 100-shaft `MAX_DOZENS` case solves in well
under that), so recomputing per request is simpler than building storage
that isn't earning its keep yet — see `core/grouping.py`'s docstring for
what would need to change if that stops being true.

A shaft left over after solving used to just sit in `unusedShafts` even
when plenty of it could still form a smaller matched group —
`min_group_size` (Configuration's "Usable group threshold (shafts)")
existed as a stored, editable `param_set` column from the start but
nothing ever read it; the field looked wired up but did nothing. It's
real now, via `core/grouping.py`'s `solve_leftover_groups`: repeatedly
extract the single best remaining match (`solve_max_set`, so each
extraction is itself exactly optimal, not a heuristic pick) until what's
left is smaller than the threshold. Under `MAX_DOZENS` this runs on
`solve_max_dozens`'s leftover shafts, on top of the dozens already
found; under `MAX_SET` — despite the name, always **every** usable
match, not just the single largest, confirmed product decision — it runs
on the whole candidate pool directly, since there's no separate "primary"
group to salvage around. Either way, every group carries an `isDozen`
flag (true only for an actual `solve_max_dozens` dozen) so the frontend,
and a built set's own `targetSize`, don't mistake a salvaged group of 5
for a dozen that came up short.

### Frontend (`static/js/`)

No build step; `static/index.html` loads `app.js` as an ES module. `app.js`
is a ~20-line hash router (`#/batches`, `#/batches/{id}`, `#/config`) —
since it's a single page, navigating between tabs does **not** reload
`app.js` or re-fetch other modules already imported. A backend change is
picked up on the next full reload; a *frontend* change needs the user to
actually reload the tab. `app/main.py` sets `Cache-Control: no-cache` on
`/`, `/js/*`, `/css/*` so a plain reload (not a hard-refresh) is enough —
without it, a browser can keep serving a stale cached JS file indefinitely.

- `focusring.js` — `buildRing(rows, mode, pass)` is the entire traversal
  order for both entry modes; Mode 2's second pass is just a different
  ring over the same DOM.
- `entrygrid.js` — the keyboard entry grid. Enter/Tab both call
  `commitField()` explicitly *and* trigger it again via the blur that
  `ring.advance()` causes; `commitField`'s `pending` map collapses these
  into one PATCH (a real bug, found via Playwright, not by inspection —
  see the comment there for why both call sites are still needed).
  Weight is two live-linked columns (grams/grains): typing in one updates
  the other's *displayed* value and its `lastSaved`, so tabbing through an
  untouched sibling commits nothing; only the field actually typed into is
  sent, with its own unit.
- `batches.js` / `config.js` — list views sort/reorder by re-rendering
  from the server's response, never by re-fetching.
- `tablesort.js` — the one click-to-sort-by-header mechanism, shared by
  every sortable table (the Batches list, the Sets tab's candidate picker
  and built-set member list, and each Analysis group's member table).
  Owns sort state, the header click handling, and the ^/v indicator;
  hands back a `sortRows(items)` the caller applies to its own array and
  turns into DOM however suits that table -- most tables just clear and
  rebuild `tbody`, but the candidate picker instead *reorders its
  existing* `<tr>` elements (`tbody.appendChild` on an attached node
  moves it), since rebuilding would blow away any checkbox someone had
  already ticked. `shaftinfo.js`'s shared shaft-info column list (the
  same 11 columns behind three different tables) carries a `sortValue`
  per column separate from its display `get` -- e.g. `#` sorts by
  `[batchNo, seq]`, never the label string (`"19-100" < "19-20"` as
  text, same rule as `core/labels.py`).
- `sets.js` — the manual set builder. The candidate table and the built-
  sets list each trigger the other's refresh (building consumes shafts
  the candidate table shows; disbanding returns them), so neither call
  site re-renders on its own without telling the other.
- `analysis.js` — runs `GET /api/analysis` and renders each group with a
  "Build this set" button that `POST`s to `/api/sets` with that group's
  member ids — the same call `sets.js` makes, just with pre-selected
  members instead of checkboxes. A successful build re-runs the analysis
  automatically, since committing bumps `pool_version` and the just-shown
  result is stale by definition at that point. A group's `isDozen` flag
  (see `repo_analysis.run_analysis`) picks the card's title format and
  the built set's `targetSize` — `body.dozenSize` for a real dozen,
  `group.size` for a salvaged leftover match, never the other way
  around, or a 5-shaft leftover would get tagged as if it fell short of
  a 12-shaft target it was never trying to hit. The build form's Notes
  field is pre-filled with the exact parameters used (objective,
  tolerances, pool filter, and for a leftover match, the usable-group
  threshold) as an editable starting point, since a committed set has no
  lasting link back to the `param_set` that produced it. The full
  `param_set` editor (formerly Configuration's own section) lives here
  too, in a collapsed "Edit parameters" `<details>` — it edits whichever
  set the page's own "Parameter set" `<select>` has chosen rather than a
  second picker of its own, and a successful save or "Save as new"
  re-runs the analysis, same as building a set does.

## Design decisions worth knowing before changing

- **Grouping objective is user-selectable** (all matched sets / most
  complete dozens; `MAX_SET` in the database and API, unchanged) — the
  spec's own proposed "dozens" fix
  (`floor(size/12)` scored first) is provably argmax-identical to plain
  largest-count and was verified to do nothing. The real "most complete
  dozens" problem is disjoint set-packing across the whole partition, not
  a single-window search — a single biggest-window pick can strand shafts
  a second, non-overlapping dozen elsewhere in the pool needed, which
  only a solver considering every dozen jointly avoids; the clean,
  guaranteed demonstration of that is the synthetic 24-shaft case in
  `tests/test_grouping.py` (`test_max_dozens_finds_two_where_a_single_
  window_search_would_find_one`), not the real workbook data, since the
  real data's own achievable count depends on tolerance and isn't a fixed
  property of the algorithm. This is *why* the project is Python rather
  than Node. `tests/test_grouping.py`'s golden regression still pins the
  real workbook's own exact figure (1 dozen at the shipped 3.000 lb/0.50 g
  defaults, CP-SAT status `OPTIMAL`) so it can never silently drift.
  The box constraint is a strict `<` on spread, not `<=`: a group whose
  extremes sit exactly at the tolerance doesn't qualify, matching what
  "a 3 lb tolerance" means to an archer — confirmed product decision,
  see `core/grouping.py`'s `_add_box_constraints`.
- **A matched set may span batches, but only within one (diameter, wood)
  pair** — confirmed product decision, not a default worth relaxing casually.
- **`specMin` stays 54.0 lb**, one pound below the advertised 55 lb floor —
  confirmed deliberate, matches the workbook's own `ANALYSIS!B5`.
- Every UI copy change and every backend change has been verified against
  a real, running browser session (Playwright) before being called done —
  several real bugs (a focus-ring double-commit race, a DOM-attachment
  order bug, a stale `--reload` process) were only caught this way, not by
  reading the code.

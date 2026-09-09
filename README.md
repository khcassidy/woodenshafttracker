# Shaft Tracker

Shaft Tracker is a local web tool for archers. It tracks each wooden
arrow shaft you buy, records its spine and weight, and groups shafts
into matched sets. A matched set is a group of shafts with closely
similar spine and weight, ready to fletch together.

Spine is a measure of how much a shaft bends under a fixed load. Archers
match spine and weight across a set of arrows so the arrows fly the
same way.

## What it does

- Records each batch of shafts you buy, and each shaft's spine and
  weight.
- Lets you build matched sets by hand, on the Sets tab.
- Finds matched sets for you, on the Analysis tab. A solver searches
  for the largest matched set, or the most complete dozens (full or
  partial 12-arrow sets), across a whole batch.
- Replaces a hand-built spreadsheet. The spreadsheet's own calculation
  rules are the reference the analysis engine matches.

## Why it exists

A spreadsheet can calculate spine and weight, but it cannot search
every possible grouping for the best matched set. A single spreadsheet
formula can miss a second good set elsewhere in the same batch. Shaft
Tracker adds a real solver for that search.

## Stack

- Backend: Python, FastAPI, SQLite.
- Frontend: static HTML and CSS, plain JavaScript. There is no build
  step and no frontend framework.
- Solver: Google OR-Tools' CP-SAT solver, a constraint-based
  optimization solver, for the analysis engine.

## Quick start

This project needs Python 3.11 or later. Run these commands from the
project root, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python run.py --reload
```

The last command starts the dev server. It prints a local network
address, so you can also open the app from a phone or tablet at the
workbench.

## Tests

Run the full test suite with this command:

```powershell
pytest
```

## Project layout

- `core/` — the calculation and solver logic. This part touches no
  database and no web framework, so its tests run without either.
- `app/` — the FastAPI backend: the API routes and the database layer.
- `static/` — the frontend: HTML, CSS, and JavaScript modules.
- `tests/` — the automated test suite.
- `scripts/` — command-line tools, such as the workbook importer and
  the database backup script.
- `deploy/` — a self-contained copy of the app for deployment to a
  server. See [deploy/README.md](deploy/README.md).
- `planning/` — the original spreadsheet and design documents this
  project replaces.

## Data

Shaft Tracker stores your data in a local SQLite file,
`shafttracker.db`. Git ignores this file, so it stays out of the
repository. Back it up first, with this command, before any risky
change:

```powershell
python scripts\backup.py
```

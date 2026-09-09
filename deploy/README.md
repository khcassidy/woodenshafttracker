# Shaft Tracker — deployment folder

This folder holds the files needed to run Shaft Tracker on a server. It
does not include tests, planning documents, or import scripts, since the
server does not need them.

## First-time setup on the server

1. Copy this whole folder to the server.
2. Check the Python version already on the server:

   ```
   python3 --version
   ```

   Python 3.9 or later works. `requirements.txt` includes
   `eval_type_backport` for Python 3.9, a small package that lets
   Pydantic and FastAPI read this project's `X | None`-style type hints
   on a Python older than 3.10. You do not need Python 3.11 just to run
   the server — that version is only the baseline used for development
   of this project.
3. Create a virtual environment and install dependencies:

   ```
   python3 -m venv .venv
   source .venv/bin/activate             # Linux/macOS
   .\.venv\Scripts\Activate.ps1          # Windows
   python -m pip install -r requirements.txt
   ```

   The `ortools` package needs glibc 2.28 or later on Linux. Slackware
   15.0 ships glibc 2.33, so this is not a concern on that distribution.

## Start the server

```
python run.py
```

The command prints the LAN URL to use from another device. The server
listens on port 8765 by default. Set `SHAFTTRACKER_PORT` or
`SHAFTTRACKER_HOST` to change this.

## Run automatically at boot (Slackware)

`rc.shaft` is a Slackware-style `rc.<name>` script with
`start`/`stop`/`restart`/`status` commands. It assumes the deployment
folder is at `/opt/shafttracker` and runs `python3` directly, matching
a server where dependencies were installed into the system Python
rather than a virtual environment — edit the `DIR` and `PYTHON`
variables at the top of the file if your server differs.

1. Install it:
   ```
   cp rc.shaft /etc/rc.d/rc.shaft
   chmod +x /etc/rc.d/rc.shaft
   ```
2. Start it manually to check it works:
   ```
   /etc/rc.d/rc.shaft start
   /etc/rc.d/rc.shaft status
   ```
3. To start Shaft Tracker on every boot, add this line to
   `/etc/rc.d/rc.local` — Slackware's `rc.M` only calls its own fixed
   set of core `rc.<name>` scripts, so a new one needs `rc.local` to
   be started automatically:
   ```
   /etc/rc.d/rc.shaft start
   ```

Output from the running server goes to `/var/log/shafttracker.log`.

## Data

`shafttracker.db` in this folder is a snapshot of the data taken on
2026-09-08. The server reads and writes this file directly at the path
`shafttracker.db`, relative to where you run `python run.py`. Set the
`SHAFTTRACKER_DB` environment variable to point at a different file.

## Backups

Run this command on the server on a regular basis, and before any
migration or bulk edit:

```
python scripts/backup.py
```

The script copies the database through SQLite's own backup API, so it
is safe to run while the server is live. Never copy `shafttracker.db`
with a plain file copy — the database uses write-ahead logging, and a
raw copy taken mid-write can be corrupt.

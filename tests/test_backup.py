import sqlite3

from scripts.backup import backup, main


def _make_source_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    from app.db.migrate import migrate

    migrate(conn)
    conn.execute(
        "INSERT INTO batch(batch_no, seq_width, expected_count) VALUES (99, 2, 1)"
    )
    conn.commit()
    conn.close()


def test_backup_produces_a_complete_consistent_copy(tmp_path):
    source = tmp_path / "source.db"
    _make_source_db(source)

    dest_dir = tmp_path / "backups"
    dest_path = backup(source, dest_dir)

    assert dest_path.exists()
    assert dest_path.parent == dest_dir
    assert dest_path.stat().st_size > 0

    conn = sqlite3.connect(dest_path)
    row = conn.execute("SELECT batch_no FROM batch WHERE batch_no = 99").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 99


def test_backup_filename_has_a_utc_timestamp(tmp_path):
    source = tmp_path / "source.db"
    _make_source_db(source)
    dest_path = backup(source, tmp_path / "backups")
    assert dest_path.name.startswith("shafttracker-")
    assert dest_path.name.endswith(".db")


def test_main_reports_missing_source_db(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.db"
    exit_code = main(["--db", str(missing), "--out", str(tmp_path / "backups")])
    assert exit_code == 1
    assert "nothing to back up" in capsys.readouterr().err


def test_main_succeeds_with_explicit_paths(tmp_path, capsys):
    source = tmp_path / "source.db"
    _make_source_db(source)
    out_dir = tmp_path / "backups"
    exit_code = main(["--db", str(source), "--out", str(out_dir)])
    assert exit_code == 0
    assert "Backed up" in capsys.readouterr().out
    assert list(out_dir.glob("shafttracker-*.db"))

import sqlite3

import pytest

from app.db.migrate import migrate


def _insert_batch(db, batch_no=19, seq_width=2, expected_count=1):
    db.execute(
        "INSERT INTO batch(batch_no, seq_width, expected_count) VALUES (?, ?, ?)",
        (batch_no, seq_width, expected_count),
    )
    db.commit()
    return db.execute(
        "SELECT id FROM batch WHERE batch_no = ?", (batch_no,)
    ).fetchone()["id"]


def test_migrate_sets_user_version(db):
    assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_migrate_is_idempotent(db):
    assert migrate(db) == 2
    assert migrate(db) == 2


def test_diameter_option_seed_includes_unknown_sentinel(db):
    row = db.execute("SELECT * FROM diameter_option WHERE id = 0").fetchone()
    assert row["is_unknown"] == 1
    assert row["sixty_fourths"] is None


def test_wood_option_seed_includes_unknown_sentinel(db):
    row = db.execute("SELECT * FROM wood_option WHERE id = 0").fetchone()
    assert row["is_unknown"] == 1


def test_unknown_sentinel_is_unique_per_lookup(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO diameter_option(id,label,sort_order,is_unknown) "
            "VALUES (99,'Also unknown',998,1)"
        )


def test_default_param_set_matches_workbook(db):
    row = db.execute("SELECT * FROM param_set WHERE is_default = 1").fetchone()
    assert row["spine_tol_mlb"] == 3000
    assert row["weight_tol_cg"] == 50
    assert row["spec_min_mlb"] == 54000
    assert row["spec_max_mlb"] == 60000
    assert row["ab_tol_cp"] == 100
    assert row["min_group_size"] == 3


def test_only_one_default_param_set_allowed(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO param_set
               (name, is_default, spine_tol_mlb, weight_tol_cg,
                spec_min_mlb, spec_max_mlb, ab_tol_cp)
               VALUES ('Second default', 1, 3000, 50, 54000, 60000, 100)"""
        )


def test_shaft_requires_a_batch(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO shaft(batch_id, seq, label) VALUES (999, 1, '999-01')"
        )


def test_avg_spine_mlb_check_rejects_wrong_value(db):
    batch_id = _insert_batch(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO shaft
               (batch_id, seq, label, spine_count, spine_sum_cp,
                spine_min_cp, spine_max_cp, avg_spine_mlb, spine_spread_cp)
               VALUES (?, 1, '19-01', 2, 11100, 5500, 5600, 55501, 100)""",
            (batch_id,),
        )


def test_avg_spine_mlb_check_accepts_correct_value(db):
    batch_id = _insert_batch(db)
    db.execute(
        """INSERT INTO shaft
           (batch_id, seq, label, spine_count, spine_sum_cp,
            spine_min_cp, spine_max_cp, avg_spine_mlb, spine_spread_cp)
           VALUES (?, 1, '19-01', 2, 11100, 5500, 5600, 55500, 100)""",
        (batch_id,),
    )
    db.commit()
    row = db.execute(
        "SELECT avg_spine_mlb FROM shaft WHERE label = '19-01'"
    ).fetchone()
    assert row["avg_spine_mlb"] == 55500


def test_consumed_set_id_and_consumed_at_travel_together(db):
    batch_id = _insert_batch(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO shaft(batch_id, seq, label, consumed_set_id) "
            "VALUES (?, 1, '19-01', 1)",
            (batch_id,),
        )


def test_pool_version_bumps_on_shaft_insert(db):
    before = db.execute(
        "SELECT int_value FROM app_meta WHERE key='pool_version'"
    ).fetchone()[0]
    batch_id = _insert_batch(db)
    db.execute(
        "INSERT INTO shaft(batch_id, seq, label) VALUES (?, 1, '19-01')",
        (batch_id,),
    )
    after = db.execute(
        "SELECT int_value FROM app_meta WHERE key='pool_version'"
    ).fetchone()[0]
    assert after == before + 1


def test_pool_version_bumps_on_shaft_update(db):
    batch_id = _insert_batch(db)
    db.execute(
        "INSERT INTO shaft(batch_id, seq, label) VALUES (?, 1, '19-01')",
        (batch_id,),
    )
    before = db.execute(
        "SELECT int_value FROM app_meta WHERE key='pool_version'"
    ).fetchone()[0]
    db.execute("UPDATE shaft SET notes = 'x' WHERE label = '19-01'")
    after = db.execute(
        "SELECT int_value FROM app_meta WHERE key='pool_version'"
    ).fetchone()[0]
    assert after == before + 1


def test_pool_version_bumps_on_shaft_delete(db):
    batch_id = _insert_batch(db)
    db.execute(
        "INSERT INTO shaft(batch_id, seq, label) VALUES (?, 1, '19-01')",
        (batch_id,),
    )
    before = db.execute(
        "SELECT int_value FROM app_meta WHERE key='pool_version'"
    ).fetchone()[0]
    db.execute("DELETE FROM shaft WHERE label = '19-01'")
    after = db.execute(
        "SELECT int_value FROM app_meta WHERE key='pool_version'"
    ).fetchone()[0]
    assert after == before + 1


def test_pool_version_bumps_on_spine_reading_insert(db):
    batch_id = _insert_batch(db)
    db.execute(
        "INSERT INTO shaft(batch_id, seq, label) VALUES (?, 1, '19-01')",
        (batch_id,),
    )
    shaft_id = db.execute(
        "SELECT id FROM shaft WHERE label='19-01'"
    ).fetchone()["id"]
    before = db.execute(
        "SELECT int_value FROM app_meta WHERE key='pool_version'"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO shaft_spine_reading(shaft_id, ordinal, value_cp, entered_text) "
        "VALUES (?, 1, 5600, '56')",
        (shaft_id,),
    )
    after = db.execute(
        "SELECT int_value FROM app_meta WHERE key='pool_version'"
    ).fetchone()[0]
    assert after == before + 1


def test_shaft_entry_v_pivots_readings_to_columns(db):
    batch_id = _insert_batch(db)
    db.execute(
        """INSERT INTO shaft
           (batch_id, seq, label, spine_count, spine_sum_cp,
            spine_min_cp, spine_max_cp, avg_spine_mlb, spine_spread_cp)
           VALUES (?, 1, '19-01', 2, 11100, 5500, 5600, 55500, 100)""",
        (batch_id,),
    )
    shaft_id = db.execute(
        "SELECT id FROM shaft WHERE label='19-01'"
    ).fetchone()["id"]
    db.execute(
        "INSERT INTO shaft_spine_reading(shaft_id, ordinal, value_cp, entered_text) "
        "VALUES (?, 1, 5600, '56')",
        (shaft_id,),
    )
    db.execute(
        "INSERT INTO shaft_spine_reading(shaft_id, ordinal, value_cp, entered_text) "
        "VALUES (?, 2, 5500, '55')",
        (shaft_id,),
    )
    row = db.execute("SELECT * FROM shaft_entry_v WHERE label = '19-01'").fetchone()
    assert row["spine_a_cp"] == 5600
    assert row["spine_b_cp"] == 5500
    assert row["avg_spine_mlb"] == 55500


def test_analysable_pool_predicate_excludes_junk_and_unmeasured(db):
    batch_id = _insert_batch(db, expected_count=2)
    db.execute(
        """INSERT INTO shaft
           (batch_id, seq, label, spine_count, spine_sum_cp,
            spine_min_cp, spine_max_cp, avg_spine_mlb, spine_spread_cp,
            weight_cg, weight_text, weight_unit, straightness)
           VALUES (?, 1, '19-01', 2, 11100, 5500, 5600, 55500, 100,
                   2323, '23.23', 'g', 'JUNK')""",
        (batch_id,),
    )
    db.execute(
        """INSERT INTO shaft
           (batch_id, seq, label, spine_count, spine_sum_cp,
            spine_min_cp, spine_max_cp, avg_spine_mlb, spine_spread_cp,
            weight_cg, weight_text, weight_unit, straightness)
           VALUES (?, 2, '19-02', 2, 11600, 5800, 5800, 58000, 0,
                   2470, '24.70', 'g', 'OK')""",
        (batch_id,),
    )
    rows = db.execute(
        """SELECT label FROM shaft
           WHERE consumed_set_id IS NULL
             AND avg_spine_mlb IS NOT NULL
             AND weight_cg IS NOT NULL
             AND (straightness IS NULL OR straightness <> 'JUNK')"""
    ).fetchall()
    assert [r["label"] for r in rows] == ["19-02"]

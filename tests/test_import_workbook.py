"""The golden suite: every figure here was verified against the workbook's
own ANALYSIS tab before this test was written. A pass here means the
importer reproduces the workbook exactly; a failure means either the
importer or this fixture has drifted from the source of truth."""

from pathlib import Path

import pytest

from app.io.xlsx_read import open_workbook
from scripts.import_workbook import build_report, commit_batch, read_batch_sheet

WORKBOOK_PATH = Path(__file__).resolve().parent.parent / "planning" / (
    "Arrow Batch 19 20 20260901.xlsx"
)


@pytest.fixture(scope="module")
def wb():
    workbook = open_workbook(WORKBOOK_PATH)
    yield workbook
    workbook.close()


@pytest.fixture(scope="module")
def report19(wb):
    batch_no, nominal_label, rows = read_batch_sheet(wb, "BATCH19")
    return build_report(batch_no, nominal_label, rows)


@pytest.fixture(scope="module")
def report20(wb):
    batch_no, nominal_label, rows = read_batch_sheet(wb, "BATCH20")
    return build_report(batch_no, nominal_label, rows)


def test_batch19_identity(report19):
    assert report19["batch_no"] == 19
    assert report19["nominal_label"] == "55-60#"
    assert report19["count"] == 50
    assert report19["errors"] == []


def test_batch20_identity(report20):
    assert report20["batch_no"] == 20
    assert report20["nominal_label"] == "55-60#"
    assert report20["count"] == 50
    assert report20["errors"] == []


def test_batch19_qc_matches_workbook(report19):
    assert report19["in_spec"] == 37
    assert report19["below_floor"] == 13
    assert report19["above_ceiling"] == 0


def test_batch20_qc_matches_workbook(report20):
    assert report20["in_spec"] == 38
    assert report20["below_floor"] == 12
    assert report20["above_ceiling"] == 0


def test_combined_qc_matches_workbook(report19, report20):
    assert report19["count"] + report20["count"] == 100
    assert report19["in_spec"] + report20["in_spec"] == 75
    assert report19["below_floor"] + report20["below_floor"] == 25
    assert report19["above_ceiling"] + report20["above_ceiling"] == 0


def test_batch19_weight_stats_cg(report19):
    assert report19["weight_min_cg"] == 2118
    assert report19["weight_max_cg"] == 2676
    assert report19["weight_sum_cg"] == 118242


def test_batch20_weight_stats_cg(report20):
    assert report20["weight_min_cg"] == 2146
    assert report20["weight_max_cg"] == 2609
    assert report20["weight_sum_cg"] == 117925


def test_combined_weight_stats_cg(report19, report20):
    combined_min = min(report19["weight_min_cg"], report20["weight_min_cg"])
    combined_max = max(report19["weight_max_cg"], report20["weight_max_cg"])
    assert combined_min == 2118
    assert combined_max == 2676
    assert report19["weight_sum_cg"] + report20["weight_sum_cg"] == 236167


def test_combined_mean_avg_spine_is_exactly_55_22_lb(report19, report20):
    # ANALYSIS!D15 shows 55.22 lb combined. In minor units the mean is
    # exactly 5522000 mlb / 100 -- no float noise, unlike the workbook cell.
    total_mlb = report19["avg_spine_sum_mlb"] + report20["avg_spine_sum_mlb"]
    assert total_mlb == 5522000


def test_only_shaft_20_50_fails_ab_consistency(report19, report20):
    # The workbook flags exactly one shaft: 20-50, at a 2.0 lb A/B spread
    # against a 1.0 lb tolerance (100 cp).
    inconsistent = [
        p["label"]
        for p in report19["parsed"] + report20["parsed"]
        if p["derived"].spine_spread_cp > 100
    ]
    assert inconsistent == ["20-50"]
    shaft_20_50 = next(p for p in report20["parsed"] if p["label"] == "20-50")
    assert shaft_20_50["derived"].spine_spread_cp == 200


def test_all_200_spine_readings_are_multiples_of_half_pound(report19, report20):
    for p in report19["parsed"] + report20["parsed"]:
        assert p["spine_a_cp"] % 50 == 0
        if p["spine_b_cp"] is not None:
            assert p["spine_b_cp"] % 50 == 0


def test_no_weight_exceeds_two_decimal_places(report19, report20):
    # A UnitError with code TOO_MANY_DP would have landed in report["errors"],
    # which test_batch{19,20}_identity already asserts is empty. This test
    # pins the specific shape: every raw weight string has at most 2 dp.
    for p in report19["parsed"] + report20["parsed"]:
        if "." in p["weight_raw"]:
            assert len(p["weight_raw"].split(".")[1]) <= 2


def test_shaft_19_01_matches_known_values(report19):
    row = next(p for p in report19["parsed"] if p["label"] == "19-01")
    assert row["spine_a_cp"] == 5600
    assert row["spine_b_cp"] == 5500
    assert row["derived"].avg_spine_mlb == 55500
    assert row["weight_cg"] == 2323


def test_commit_batch_writes_100_shafts_and_passes_every_check(db, report19, report20):
    commit_batch(db, report19, diameter_label=None, wood_label=None)
    commit_batch(db, report20, diameter_label=None, wood_label=None)
    db.commit()

    total = db.execute("SELECT COUNT(*) AS n FROM shaft").fetchone()["n"]
    assert total == 100

    readings = db.execute("SELECT COUNT(*) AS n FROM shaft_spine_reading").fetchone()["n"]
    assert readings == 200

    row = db.execute("SELECT * FROM shaft_entry_v WHERE label = '19-01'").fetchone()
    assert row["spine_a_cp"] == 5600
    assert row["spine_b_cp"] == 5500
    assert row["avg_spine_mlb"] == 55500
    assert row["weight_cg"] == 2323


def test_commit_batch_defaults_to_unknown_diameter_and_wood(db, report19):
    commit_batch(db, report19, diameter_label=None, wood_label=None)
    db.commit()
    row = db.execute("SELECT diameter_id, wood_id FROM shaft WHERE label = '19-01'").fetchone()
    assert row["diameter_id"] == 0
    assert row["wood_id"] == 0


def test_commit_batch_assigns_named_diameter_and_wood(db, report19):
    commit_batch(db, report19, diameter_label='11/32"', wood_label="Northern Pine")
    db.commit()
    row = db.execute("SELECT diameter_id, wood_id FROM shaft WHERE label = '19-01'").fetchone()
    diameter_id = db.execute(
        "SELECT id FROM diameter_option WHERE label = '11/32\"'"
    ).fetchone()["id"]
    wood_id = db.execute(
        "SELECT id FROM wood_option WHERE label = 'Northern Pine'"
    ).fetchone()["id"]
    assert row["diameter_id"] == diameter_id
    assert row["wood_id"] == wood_id


def test_commit_batch_stores_batch_metadata(db, report19):
    commit_batch(db, report19, diameter_label=None, wood_label=None)
    db.commit()
    row = db.execute("SELECT * FROM batch WHERE batch_no = 19").fetchone()
    assert row["nominal_spine_label"] == "55-60#"
    assert row["nominal_min_lb"] == 55
    assert row["nominal_max_lb"] == 60
    assert row["seq_width"] == 2
    assert row["expected_count"] == 50

import json

import pytest


@pytest.fixture
def batch_with_data(client):
    r = client.post(
        "/api/batches",
        json={"batchNo": 19, "expectedCount": 2, "nominalSpineLabel": "55-60#"},
    )
    batch_id = r.json()["id"]
    client.patch(
        f"/api/batches/{batch_id}/shafts/1",
        json={"spineA": "56", "spineB": "55", "weight": "23.23", "weightUnit": "g"},
    )
    client.patch(
        f"/api/batches/{batch_id}/shafts/2",
        json={"spineA": "58", "weight": "350", "weightUnit": "gr"},
    )
    return batch_id


# ---- export ----


def test_export_json_shape(client, batch_with_data):
    r = client.get("/api/export/json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert len(data["batches"]) == 1
    batch = data["batches"][0]
    assert batch["batchNo"] == 19
    assert batch["nominalSpineLabel"] == "55-60#"
    shafts = {s["seq"]: s for s in batch["shafts"]}
    assert shafts[1]["spineA"] == "56"
    assert shafts[1]["weightText"] == "23.23"
    assert shafts[1]["weightUnit"] == "g"
    assert shafts[2]["weightText"] == "350"
    assert shafts[2]["weightUnit"] == "gr"


def test_export_csv_all_shafts(client, batch_with_data):
    r = client.get("/api/export/csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text.lstrip("﻿")
    lines = text.strip().split("\r\n")
    assert lines[0].split(",")[:3] == ["Batch", "Seq", "Label"]
    assert any("19-01" in line for line in lines)
    assert any("23.23" in line for line in lines)


def test_export_batch_csv(client, batch_with_data):
    r = client.get(f"/api/batches/{batch_with_data}/export/csv")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    text = r.text.lstrip("﻿")
    assert "19-01" in text
    assert "19-02" in text


def test_export_batch_csv_missing_batch_404(client):
    r = client.get("/api/batches/999/export/csv")
    assert r.status_code == 404


# ---- import: CSV ----

CSV_TEXT = (
    "Batch,Seq,Diameter,Wood,SpineA,SpineB,WeightG,Straightness,Notes\r\n"
    '30,1,"11/32""",Northern Pine,56,55,23.23,OK,first\r\n'
    '30,2,"11/32""",Northern Pine,58,58,24.70,,second\r\n'
)


def test_import_csv_preview_reports_new_batch(client):
    r = client.post(
        "/api/import/preview",
        files={"file": ("shafts.csv", CSV_TEXT, "text/csv")},
        data={"format": "csv"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["batchesNew"] == [30]
    assert body["report"]["rowCount"] == 2
    assert body["report"]["errors"] == []
    assert body["token"]


def test_import_csv_commit_creates_batch_and_shafts(client):
    preview = client.post(
        "/api/import/preview",
        files={"file": ("shafts.csv", CSV_TEXT, "text/csv")},
        data={"format": "csv"},
    ).json()
    r = client.post("/api/import/commit", json={"token": preview["token"]})
    assert r.status_code == 200
    assert r.json()["batchesCreated"] == 1
    assert r.json()["shaftsWritten"] == 2

    batches = client.get("/api/batches").json()
    batch = next(b for b in batches if b["batchNo"] == 30)
    shafts = client.get(f"/api/batches/{batch['id']}/shafts").json()
    row1 = next(s for s in shafts if s["seq"] == 1)
    assert row1["spineACp"] == 5600
    assert row1["spineBCp"] == 5500
    assert row1["weightCg"] == 2323
    assert row1["straightness"] == "OK"
    assert row1["notes"] == "first"


def test_import_csv_unknown_diameter_reported_as_error(client):
    bad_csv = "Batch,Seq,Diameter,SpineA\r\n40,1,9/16 made up,56\r\n"
    r = client.post(
        "/api/import/preview",
        files={"file": ("bad.csv", bad_csv, "text/csv")},
        data={"format": "csv"},
    )
    body = r.json()
    assert len(body["report"]["errors"]) == 1
    assert "9/16 made up" in body["report"]["errors"][0]


def test_import_csv_commit_rejected_when_preview_had_errors(client):
    bad_csv = "Batch,Seq,Diameter,SpineA\r\n40,1,not a real diameter,56\r\n"
    preview = client.post(
        "/api/import/preview",
        files={"file": ("bad.csv", bad_csv, "text/csv")},
        data={"format": "csv"},
    ).json()
    r = client.post("/api/import/commit", json={"token": preview["token"]})
    assert r.status_code == 400


def test_import_csv_skips_rows_for_existing_batch_no(client, batch_with_data):
    csv_text = "Batch,Seq,SpineA\r\n19,1,50\r\n"  # batch 19 already exists
    r = client.post(
        "/api/import/preview",
        files={"file": ("shafts.csv", csv_text, "text/csv")},
        data={"format": "csv"},
    )
    body = r.json()
    assert body["report"]["batchesSkippedExisting"] == [19]
    assert body["report"]["batchesNew"] == []
    assert body["report"]["rowCount"] == 0


def test_import_commit_cannot_run_twice(client):
    preview = client.post(
        "/api/import/preview",
        files={"file": ("shafts.csv", CSV_TEXT, "text/csv")},
        data={"format": "csv"},
    ).json()
    client.post("/api/import/commit", json={"token": preview["token"]})
    r = client.post("/api/import/commit", json={"token": preview["token"]})
    assert r.status_code == 400


def test_import_commit_unknown_token_400(client):
    r = client.post("/api/import/commit", json={"token": "does-not-exist"})
    assert r.status_code == 400


# ---- import: JSON round trip ----


def test_import_json_round_trips_an_export(client, batch_with_data):
    export = client.get("/api/export/json").json()
    export["batches"][0]["batchNo"] = 77  # avoid colliding with the existing batch

    preview = client.post(
        "/api/import/preview",
        files={"file": ("backup.json", json.dumps(export), "application/json")},
        data={"format": "json"},
    ).json()
    assert preview["report"]["batchesNew"] == [77]

    commit = client.post("/api/import/commit", json={"token": preview["token"]}).json()
    assert commit["batchesCreated"] == 1

    batches = client.get("/api/batches").json()
    new_batch = next(b for b in batches if b["batchNo"] == 77)
    shafts = client.get(f"/api/batches/{new_batch['id']}/shafts").json()
    row2 = next(s for s in shafts if s["seq"] == 2)
    assert row2["weightText"] == "350"
    assert row2["weightUnit"] == "gr"
    assert row2["weightCg"] == 2268  # 350 gr -> 22.68 g, matching core/units.py

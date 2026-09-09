import pytest


@pytest.fixture
def batch(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 4})
    return r.json()


def test_insert_shaft_in_the_middle_shifts_and_relabels_later_shafts(client, batch):
    batch_id = batch["id"]
    client.patch(f"/api/batches/{batch_id}/shafts/2", json={"spineA": "56"})
    client.patch(f"/api/batches/{batch_id}/shafts/3", json={"spineA": "58"})

    r = client.post(f"/api/batches/{batch_id}/shafts:insert", json={"afterSeq": 2})
    assert r.status_code == 200
    inserted = r.json()
    assert inserted["seq"] == 3
    assert inserted["label"] == "19-03"
    assert inserted["spineACp"] is None  # the new row is blank

    shafts = client.get(f"/api/batches/{batch_id}/shafts").json()
    labels = [s["label"] for s in shafts]
    assert labels == ["19-01", "19-02", "19-03", "19-04", "19-05"]

    # Inserted after seq 2, so seq 2 itself (spineA=56) does not move.
    unmoved = next(s for s in shafts if s["spineACp"] == 5600)
    assert unmoved["seq"] == 2
    assert unmoved["label"] == "19-02"

    # What was seq 3 (spineA=58) shifts up to seq 4 to make room.
    moved = next(s for s in shafts if s["spineACp"] == 5800)
    assert moved["seq"] == 4
    assert moved["label"] == "19-04"

    batch_after = client.get(f"/api/batches/{batch_id}").json()
    assert batch_after["expectedCount"] == 5


def test_insert_shaft_at_front(client, batch):
    batch_id = batch["id"]
    r = client.post(f"/api/batches/{batch_id}/shafts:insert", json={"afterSeq": 0})
    assert r.json()["seq"] == 1
    labels = [s["label"] for s in client.get(f"/api/batches/{batch_id}/shafts").json()]
    assert labels == ["19-01", "19-02", "19-03", "19-04", "19-05"]


def test_insert_shaft_at_end_is_equivalent_to_append(client, batch):
    batch_id = batch["id"]
    r = client.post(f"/api/batches/{batch_id}/shafts:insert", json={"afterSeq": 4})
    assert r.json()["seq"] == 5
    assert r.json()["label"] == "19-05"


def test_insert_shaft_rejects_out_of_range_after_seq(client, batch):
    batch_id = batch["id"]
    r = client.post(f"/api/batches/{batch_id}/shafts:insert", json={"afterSeq": 99})
    assert r.status_code == 400


def test_insert_shaft_rejects_growth_past_fixed_seq_width(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 99})
    batch_id = r.json()["id"]
    r = client.post(f"/api/batches/{batch_id}/shafts:insert", json={"afterSeq": 99})
    assert r.status_code == 400


def test_delete_shaft_closes_the_gap_and_relabels(client, batch):
    batch_id = batch["id"]
    client.patch(f"/api/batches/{batch_id}/shafts/3", json={"spineA": "58"})

    r = client.delete(f"/api/batches/{batch_id}/shafts/2")
    assert r.status_code == 200

    shafts = client.get(f"/api/batches/{batch_id}/shafts").json()
    labels = [s["label"] for s in shafts]
    assert labels == ["19-01", "19-02", "19-03"]

    # The shaft that had spineA=58 (originally seq 3) kept its data and is
    # now seq 2.
    moved = next(s for s in shafts if s["spineACp"] == 5800)
    assert moved["seq"] == 2
    assert moved["label"] == "19-02"

    batch_after = client.get(f"/api/batches/{batch_id}").json()
    assert batch_after["expectedCount"] == 3


def test_delete_last_shaft(client, batch):
    batch_id = batch["id"]
    r = client.delete(f"/api/batches/{batch_id}/shafts/4")
    assert r.status_code == 200
    labels = [s["label"] for s in client.get(f"/api/batches/{batch_id}/shafts").json()]
    assert labels == ["19-01", "19-02", "19-03"]


def test_delete_missing_shaft_returns_400(client, batch):
    batch_id = batch["id"]
    r = client.delete(f"/api/batches/{batch_id}/shafts/999")
    assert r.status_code == 400


def test_delete_readings_cascade_with_the_shaft(client, db, batch):
    batch_id = batch["id"]
    client.patch(f"/api/batches/{batch_id}/shafts/1", json={"spineA": "56", "spineB": "55"})
    before = db.execute("SELECT COUNT(*) AS n FROM shaft_spine_reading").fetchone()["n"]
    assert before == 2

    client.delete(f"/api/batches/{batch_id}/shafts/1")

    after = db.execute("SELECT COUNT(*) AS n FROM shaft_spine_reading").fetchone()["n"]
    assert after == 0
    shafts = client.get(f"/api/batches/{batch_id}/shafts").json()
    assert all(s["spineACp"] is None for s in shafts)

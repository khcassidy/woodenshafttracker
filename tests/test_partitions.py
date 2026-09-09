def test_empty_database_returns_empty_partition_list(client):
    r = client.get("/api/partitions")
    assert r.status_code == 200
    assert r.json() == []


def test_partition_counts_reconcile_with_measurement_and_junk_state(client):
    r = client.post(
        "/api/batches", json={"batchNo": 19, "expectedCount": 2, "diameterId": 1, "woodId": 1}
    )
    batch_id = r.json()["id"]

    client.patch(
        f"/api/batches/{batch_id}/shafts/1",
        json={"spineA": "56", "spineB": "55", "weight": "23.23"},
    )
    client.patch(f"/api/batches/{batch_id}/shafts/2", json={"straightness": "JUNK"})

    r = client.get("/api/partitions")
    partitions = r.json()
    assert len(partitions) == 1
    p = partitions[0]
    assert p["diameter"]["id"] == 1
    assert p["wood"]["id"] == 1
    assert p["total"] == 2
    assert p["available"] == 1
    assert p["junk"] == 1
    assert p["consumed"] == 0
    assert p["unmeasured"] == 0
    assert p["available"] + p["junk"] + p["consumed"] + p["unmeasured"] == p["total"]


def test_unmeasured_shaft_counted_separately_from_available(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 1})
    batch_id = r.json()["id"]
    client.patch(f"/api/batches/{batch_id}/shafts/1", json={"spineA": "56", "spineB": "56"})

    r = client.get("/api/partitions")
    p = r.json()[0]
    assert p["available"] == 0
    assert p["unmeasured"] == 1


def test_partition_shafts_lists_only_available_by_default(client):
    r = client.post(
        "/api/batches", json={"batchNo": 19, "expectedCount": 2, "diameterId": 1, "woodId": 1}
    )
    batch_id = r.json()["id"]
    client.patch(
        f"/api/batches/{batch_id}/shafts/1",
        json={"spineA": "56", "spineB": "55", "weight": "23.23"},
    )
    # shaft 2 stays unmeasured -- must not appear as a set-builder candidate

    r = client.get("/api/partitions/1/1/shafts")
    assert r.status_code == 200
    shafts = r.json()
    assert len(shafts) == 1
    assert shafts[0]["label"] == "19-01"
    assert shafts[0]["avgSpineMlb"] == 55500


def test_partition_shafts_available_only_false_includes_everything(client):
    r = client.post(
        "/api/batches", json={"batchNo": 19, "expectedCount": 2, "diameterId": 1, "woodId": 1}
    )
    batch_id = r.json()["id"]
    client.patch(
        f"/api/batches/{batch_id}/shafts/1",
        json={"spineA": "56", "spineB": "55", "weight": "23.23"},
    )

    r = client.get("/api/partitions/1/1/shafts?available_only=false")
    assert len(r.json()) == 2

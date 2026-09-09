def test_create_batch_pre_creates_blank_shaft_rows(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 5})
    assert r.status_code == 201
    batch = r.json()
    assert batch["expectedCount"] == 5
    assert batch["seqWidth"] == 2

    r = client.get(f"/api/batches/{batch['id']}/shafts")
    assert r.status_code == 200
    shafts = r.json()
    assert [s["label"] for s in shafts] == ["19-01", "19-02", "19-03", "19-04", "19-05"]
    assert all(s["spineACp"] is None and s["weightCg"] is None for s in shafts)


def test_create_batch_parses_nominal_spine_label(client):
    r = client.post(
        "/api/batches", json={"batchNo": 21, "expectedCount": 1, "nominalSpineLabel": "55-60#"}
    )
    batch = r.json()
    assert batch["nominalMinLb"] == 55
    assert batch["nominalMaxLb"] == 60


def test_create_batch_with_duplicate_batch_no_returns_clean_409(client):
    client.post("/api/batches", json={"batchNo": 19, "expectedCount": 1})
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 1})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ALREADY_EXISTS"


def test_get_batch_404_for_missing_id(client):
    r = client.get("/api/batches/999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_batch_summary_counts_available_and_junk(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 2})
    batch_id = r.json()["id"]
    client.patch(
        f"/api/batches/{batch_id}/shafts/1",
        json={"spineA": "56", "spineB": "55", "weight": "23.23"},
    )
    client.patch(f"/api/batches/{batch_id}/shafts/2", json={"straightness": "JUNK"})

    r = client.get(f"/api/batches/{batch_id}/summary")
    summary = r.json()
    assert summary["total"] == 2
    assert summary["available"] == 1
    assert summary["junk"] == 1
    assert summary["consumed"] == 0


def test_extend_batch_appends_rows_and_updates_expected_count(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 3})
    batch_id = r.json()["id"]

    r = client.post(f"/api/batches/{batch_id}/shafts:extend", json={"additionalCount": 2})
    assert r.status_code == 200
    assert r.json()["expectedCount"] == 5

    r = client.get(f"/api/batches/{batch_id}/shafts")
    labels = [s["label"] for s in r.json()]
    assert labels == ["19-01", "19-02", "19-03", "19-04", "19-05"]


def test_patch_batch_toggles_entry_mode_and_resets_pass(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 2})
    batch_id = r.json()["id"]

    r = client.patch(f"/api/batches/{batch_id}", json={"entryMode": "per_field"})
    assert r.status_code == 200
    body = r.json()
    assert body["entryMode"] == "per_field"
    assert body["entryPass"] == "spine"

    r = client.patch(f"/api/batches/{batch_id}", json={"entryMode": "per_shaft"})
    assert r.json()["entryPass"] is None


def test_patch_batch_edits_spine_label_shop_date_and_description(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 1})
    batch_id = r.json()["id"]

    shop = client.post("/api/lookups/shop", json={"label": "Bearpaw"}).json()

    r = client.patch(
        f"/api/batches/{batch_id}",
        json={
            "nominalSpineLabel": "50-55#",
            "shopId": shop["id"],
            "purchaseDate": "2026-08-14",
            "description": "Cut from the same log as batch 18.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["nominalSpineLabel"] == "50-55#"
    assert body["nominalMinLb"] == 50
    assert body["nominalMaxLb"] == 55
    assert body["shopId"] == shop["id"]
    assert body["purchaseDate"] == "2026-08-14"
    assert body["description"] == "Cut from the same log as batch 18."

    # A second, partial edit must not clobber fields it didn't mention.
    r = client.patch(f"/api/batches/{batch_id}", json={"description": "Updated note."})
    body = r.json()
    assert body["description"] == "Updated note."
    assert body["nominalSpineLabel"] == "50-55#"
    assert body["shopId"] == shop["id"]


def test_patch_batch_renames_batch_no_and_relabels_shafts(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 3})
    batch_id = r.json()["id"]

    r = client.patch(f"/api/batches/{batch_id}", json={"batchNo": 25})
    assert r.status_code == 200
    assert r.json()["batchNo"] == 25

    shafts = client.get(f"/api/batches/{batch_id}/shafts").json()
    assert [s["label"] for s in shafts] == ["25-01", "25-02", "25-03"]


def test_patch_batch_rename_to_existing_batch_no_returns_clean_409(client):
    client.post("/api/batches", json={"batchNo": 19, "expectedCount": 1})
    r = client.post("/api/batches", json={"batchNo": 20, "expectedCount": 1})
    batch_id = r.json()["id"]

    r = client.patch(f"/api/batches/{batch_id}", json={"batchNo": 19})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ALREADY_EXISTS"

    # And the shafts must not have been relabelled by the failed attempt.
    shafts = client.get(f"/api/batches/{batch_id}/shafts").json()
    assert shafts[0]["label"] == "20-01"


def test_patch_batch_edits_diameter_and_wood_without_touching_existing_shafts(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 1})
    batch_id = r.json()["id"]
    shaft_before = client.get(f"/api/batches/{batch_id}/shafts").json()[0]
    assert shaft_before["diameterId"] == 0

    r = client.patch(f"/api/batches/{batch_id}", json={"diameterId": 1, "woodId": 1})
    assert r.json()["diameterId"] == 1
    assert r.json()["woodId"] == 1

    shaft_after = client.get(f"/api/batches/{batch_id}/shafts").json()[0]
    assert shaft_after["diameterId"] == 0  # unchanged: batch edits don't cascade


def test_extend_batch_rejects_growth_past_fixed_seq_width(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 99})
    batch_id = r.json()["id"]

    r = client.post(f"/api/batches/{batch_id}/shafts:extend", json={"additionalCount": 2})
    assert r.status_code == 400


def test_delete_batch_removes_it_and_its_shafts(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 3})
    batch_id = r.json()["id"]

    r = client.delete(f"/api/batches/{batch_id}")
    assert r.status_code == 200
    assert r.json() == {"status": "deleted"}

    assert client.get(f"/api/batches/{batch_id}").status_code == 404
    assert client.get(f"/api/batches/{batch_id}/shafts").json() == []
    assert batch_id not in [b["id"] for b in client.get("/api/batches").json()]


def test_delete_batch_404_for_missing_id(client):
    r = client.delete("/api/batches/999")
    assert r.status_code == 404


def test_delete_batch_refuses_when_a_shaft_is_already_in_a_set(client):
    r = client.post(
        "/api/batches", json={"batchNo": 19, "expectedCount": 1, "diameterId": 1, "woodId": 1}
    )
    batch_id = r.json()["id"]
    client.patch(
        f"/api/batches/{batch_id}/shafts/1",
        json={"spineA": "56", "spineB": "55", "weight": "23.23"},
    )
    shaft_id = client.get(f"/api/batches/{batch_id}/shafts").json()[0]["id"]
    client.post(
        "/api/sets",
        json={"name": "Holds it hostage", "diameterId": 1, "woodId": 1, "shaftIds": [shaft_id]},
    )

    r = client.delete(f"/api/batches/{batch_id}")
    assert r.status_code == 400

    # the batch and its consumed shaft must still be there afterward
    assert client.get(f"/api/batches/{batch_id}").status_code == 200


def test_delete_batch_frees_up_its_batch_no_for_reuse(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 1})
    batch_id = r.json()["id"]
    client.delete(f"/api/batches/{batch_id}")

    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 1})
    assert r.status_code == 201

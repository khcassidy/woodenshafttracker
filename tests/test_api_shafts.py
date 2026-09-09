import pytest


@pytest.fixture
def batch(client):
    r = client.post("/api/batches", json={"batchNo": 19, "expectedCount": 6})
    return r.json()


def test_patch_omitted_field_leaves_existing_value_untouched(client, batch):
    batch_id = batch["id"]
    client.patch(f"/api/batches/{batch_id}/shafts/1", json={"spineA": "56"})
    r = client.patch(f"/api/batches/{batch_id}/shafts/1", json={"weight": "23.23"})
    row = r.json()
    assert row["spineACp"] == 5600
    assert row["weightCg"] == 2323


def test_patch_explicit_null_clears_field_and_recomputes(client, batch):
    batch_id = batch["id"]
    client.patch(
        f"/api/batches/{batch_id}/shafts/1", json={"spineA": "56", "spineB": "55"}
    )
    r = client.patch(f"/api/batches/{batch_id}/shafts/1", json={"spineB": None})
    row = r.json()
    assert row["spineBCp"] is None
    assert row["avgSpineMlb"] == 56000  # single reading: 56 lb exactly


def test_patch_rejects_json_number_for_decimal_field(client, batch):
    batch_id = batch["id"]
    r = client.patch(f"/api/batches/{batch_id}/shafts/1", json={"weight": 23.23})
    assert r.status_code == 422


def test_patch_rejects_hard_band_violation(client, batch):
    batch_id = batch["id"]
    r = client.patch(f"/api/batches/{batch_id}/shafts/1", json={"spineA": "5.00"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_BLOCKED"


def test_patch_off_step_is_a_nonblocking_warning(client, batch):
    batch_id = batch["id"]
    r = client.patch(f"/api/batches/{batch_id}/shafts/1", json={"spineA": "56.30"})
    assert r.status_code == 200
    codes = [w["code"] for w in r.json()["warnings"]]
    assert "OFF_STEP" in codes
    assert r.json()["spineACp"] == 5630


def test_patch_unusual_value_is_a_nonblocking_warning(client, batch):
    batch_id = batch["id"]
    r = client.patch(f"/api/batches/{batch_id}/shafts/1", json={"spineA": "20"})
    assert r.status_code == 200
    codes = [w["code"] for w in r.json()["warnings"]]
    assert "UNUSUAL_VALUE" in codes


def test_patch_flags_batch_outlier_once_five_siblings_exist(client, batch):
    batch_id = batch["id"]
    for seq in range(1, 6):
        client.patch(
            f"/api/batches/{batch_id}/shafts/{seq}", json={"spineA": "56", "spineB": "56"}
        )
    r = client.patch(
        f"/api/batches/{batch_id}/shafts/6", json={"spineA": "70", "spineB": "70"}
    )
    codes = [w["code"] for w in r.json()["warnings"]]
    assert "BATCH_OUTLIER" in codes


def test_patch_missing_shaft_returns_404(client, batch):
    batch_id = batch["id"]
    r = client.patch(f"/api/batches/{batch_id}/shafts/999", json={"spineA": "56"})
    assert r.status_code == 404


def test_bulk_patch_partial_failure_does_not_abort_the_rest(client, batch):
    batch_id = batch["id"]
    r = client.post(
        f"/api/batches/{batch_id}/shafts:bulk",
        json={
            "items": [
                {"seq": 1, "fields": {"spineA": "56"}},
                {"seq": 2, "fields": {"spineA": "abc"}},
            ]
        },
    )
    results = r.json()["results"]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False

    row = client.get(f"/api/batches/{batch_id}/shafts").json()[0]
    assert row["spineACp"] == 5600


def test_entry_state_per_shaft_resume(client, batch):
    batch_id = batch["id"]
    client.patch(
        f"/api/batches/{batch_id}/shafts/1",
        json={"spineA": "56", "spineB": "55", "weight": "23.23"},
    )
    r = client.get(f"/api/batches/{batch_id}/entry-state")
    state = r.json()
    assert state["mode"] == "per_shaft"
    assert state["nextFocus"] == {"seq": 2, "field": "spineA"}
    assert state["complete"] is False


def test_entry_state_per_field_mode_walks_through_passes(client):
    r = client.post(
        "/api/batches", json={"batchNo": 20, "expectedCount": 2, "entryMode": "per_field"}
    )
    batch_id = r.json()["id"]

    state = client.get(f"/api/batches/{batch_id}/entry-state").json()
    assert state["pass"] == "spine"
    assert state["nextFocus"] == {"seq": 1, "field": "spineA"}

    client.patch(f"/api/batches/{batch_id}/shafts/1", json={"spineA": "56", "spineB": "56"})
    client.patch(f"/api/batches/{batch_id}/shafts/2", json={"spineA": "57", "spineB": "57"})

    state = client.get(f"/api/batches/{batch_id}/entry-state").json()
    assert state["pass"] == "weight"
    assert state["nextFocus"] == {"seq": 1, "field": "weightG"}

    client.patch(f"/api/batches/{batch_id}/shafts/1", json={"weight": "23.23"})
    client.patch(f"/api/batches/{batch_id}/shafts/2", json={"weight": "24.00"})

    state = client.get(f"/api/batches/{batch_id}/entry-state").json()
    assert state["pass"] == "straightness"

    client.patch(f"/api/batches/{batch_id}/shafts/1", json={"straightness": "OK"})
    client.patch(f"/api/batches/{batch_id}/shafts/2", json={"straightness": "OK"})

    state = client.get(f"/api/batches/{batch_id}/entry-state").json()
    assert state["complete"] is True
    assert state["nextFocus"] is None


def test_list_shafts_sorts_by_weight(client, batch):
    batch_id = batch["id"]
    client.patch(f"/api/batches/{batch_id}/shafts/1", json={"weight": "25.00"})
    client.patch(f"/api/batches/{batch_id}/shafts/2", json={"weight": "20.00"})
    client.patch(f"/api/batches/{batch_id}/shafts/3", json={"weight": "22.50"})

    r = client.get(f"/api/batches/{batch_id}/shafts?sort=weight")
    weighed = [s for s in r.json() if s["weightCg"] is not None]
    assert [s["weightCg"] for s in weighed] == [2000, 2250, 2500]

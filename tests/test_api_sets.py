def _make_batch_with_measured_shafts(client, batch_no, count, diameter_id=1, wood_id=1):
    r = client.post(
        "/api/batches",
        json={"batchNo": batch_no, "expectedCount": count, "diameterId": diameter_id, "woodId": wood_id},
    )
    batch_id = r.json()["id"]
    shaft_ids = []
    for seq in range(1, count + 1):
        client.patch(
            f"/api/batches/{batch_id}/shafts/{seq}",
            json={"spineA": "56", "spineB": "55", "weight": "23.23"},
        )
        row = client.get(f"/api/batches/{batch_id}/shafts").json()[seq - 1]
        shaft_ids.append(row["id"])
    return batch_id, shaft_ids


def test_create_set_consumes_its_members(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 3)

    r = client.post(
        "/api/sets",
        json={"name": "Set A", "diameterId": 1, "woodId": 1, "shaftIds": shaft_ids},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["memberCount"] == 3
    assert {m["id"] for m in body["members"]} == set(shaft_ids)

    partitions = client.get("/api/partitions").json()[0]
    assert partitions["consumed"] == 3
    assert partitions["available"] == 0


def test_create_set_spanning_two_batches_in_one_partition_succeeds(client):
    _, ids_a = _make_batch_with_measured_shafts(client, 19, 2)
    _, ids_b = _make_batch_with_measured_shafts(client, 20, 2)

    r = client.post(
        "/api/sets",
        json={"name": "Mixed batch set", "diameterId": 1, "woodId": 1, "shaftIds": ids_a + ids_b},
    )
    assert r.status_code == 200
    assert r.json()["memberCount"] == 4


def test_create_set_rejects_a_shaft_outside_the_partition(client):
    _, ids_a = _make_batch_with_measured_shafts(client, 19, 1, diameter_id=1, wood_id=1)
    _, ids_b = _make_batch_with_measured_shafts(client, 20, 1, diameter_id=2, wood_id=1)

    r = client.post(
        "/api/sets",
        json={"name": "Bad set", "diameterId": 1, "woodId": 1, "shaftIds": ids_a + ids_b},
    )
    assert r.status_code == 400


def test_create_set_rejects_an_already_consumed_shaft(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 2)
    client.post("/api/sets", json={"name": "First", "diameterId": 1, "woodId": 1, "shaftIds": [shaft_ids[0]]})

    r = client.post(
        "/api/sets",
        json={"name": "Second", "diameterId": 1, "woodId": 1, "shaftIds": [shaft_ids[0], shaft_ids[1]]},
    )
    assert r.status_code == 409


def test_create_set_replays_on_repeated_idempotency_key(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 2)
    body = {
        "name": "Idempotent set",
        "diameterId": 1,
        "woodId": 1,
        "shaftIds": shaft_ids,
        "idempotencyKey": "abc-123",
    }
    first = client.post("/api/sets", json=body).json()
    second = client.post("/api/sets", json=body).json()
    assert first["id"] == second["id"]

    partitions = client.get("/api/partitions").json()[0]
    assert partitions["consumed"] == 2


def test_disband_set_returns_members_to_the_pool(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 2)
    created = client.post(
        "/api/sets", json={"name": "Temp", "diameterId": 1, "woodId": 1, "shaftIds": shaft_ids}
    ).json()

    r = client.delete(f"/api/sets/{created['id']}")
    assert r.status_code == 200
    assert r.json()["disbandedAt"] is not None

    partitions = client.get("/api/partitions").json()[0]
    assert partitions["consumed"] == 0
    assert partitions["available"] == 2


def test_purge_set_rejects_one_not_yet_disbanded(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 1)
    created = client.post(
        "/api/sets", json={"name": "Live", "diameterId": 1, "woodId": 1, "shaftIds": shaft_ids}
    ).json()

    r = client.post(f"/api/sets/{created['id']}:purge")
    assert r.status_code == 400

    assert client.get(f"/api/sets/{created['id']}").status_code == 200


def test_purge_set_removes_a_disbanded_set(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 1)
    created = client.post(
        "/api/sets", json={"name": "Temp", "diameterId": 1, "woodId": 1, "shaftIds": shaft_ids}
    ).json()
    client.delete(f"/api/sets/{created['id']}")

    r = client.post(f"/api/sets/{created['id']}:purge")
    assert r.status_code == 200

    assert client.get(f"/api/sets/{created['id']}").status_code == 404
    assert created["id"] not in {s["id"] for s in client.get("/api/sets").json()}


def test_add_members_pulls_available_shafts_into_an_active_set(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 3)
    created = client.post(
        "/api/sets",
        json={"name": "Growing", "diameterId": 1, "woodId": 1, "shaftIds": [shaft_ids[0]]},
    ).json()

    r = client.post(f"/api/sets/{created['id']}/members:add", json={"shaftIds": shaft_ids[1:]})
    assert r.status_code == 200
    body = r.json()
    assert body["memberCount"] == 3
    assert {m["id"] for m in body["members"]} == set(shaft_ids)

    partitions = client.get("/api/partitions").json()[0]
    assert partitions["consumed"] == 3


def test_add_members_rejects_a_shaft_outside_the_partition(client):
    _, ids_a = _make_batch_with_measured_shafts(client, 19, 1, diameter_id=1, wood_id=1)
    _, ids_b = _make_batch_with_measured_shafts(client, 20, 1, diameter_id=2, wood_id=1)
    created = client.post(
        "/api/sets", json={"name": "Set A", "diameterId": 1, "woodId": 1, "shaftIds": ids_a}
    ).json()

    r = client.post(f"/api/sets/{created['id']}/members:add", json={"shaftIds": ids_b})
    assert r.status_code == 400


def test_add_members_rejects_an_already_consumed_shaft(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 2)
    created = client.post(
        "/api/sets", json={"name": "Set A", "diameterId": 1, "woodId": 1, "shaftIds": [shaft_ids[0]]}
    ).json()
    client.post(
        "/api/sets", json={"name": "Set B", "diameterId": 1, "woodId": 1, "shaftIds": [shaft_ids[1]]}
    )

    r = client.post(f"/api/sets/{created['id']}/members:add", json={"shaftIds": [shaft_ids[1]]})
    assert r.status_code == 409


def test_add_members_rejects_a_disbanded_set(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 2)
    created = client.post(
        "/api/sets", json={"name": "Set A", "diameterId": 1, "woodId": 1, "shaftIds": [shaft_ids[0]]}
    ).json()
    client.delete(f"/api/sets/{created['id']}")

    r = client.post(f"/api/sets/{created['id']}/members:add", json={"shaftIds": [shaft_ids[1]]})
    assert r.status_code == 400


def test_remove_members_returns_one_shaft_to_the_pool_leaving_the_rest(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 3)
    created = client.post(
        "/api/sets", json={"name": "Shrinking", "diameterId": 1, "woodId": 1, "shaftIds": shaft_ids}
    ).json()

    r = client.post(
        f"/api/sets/{created['id']}/members:remove", json={"shaftIds": [shaft_ids[0]]}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["memberCount"] == 2
    assert body["disbandedAt"] is None
    assert shaft_ids[0] not in {m["id"] for m in body["members"]}

    partitions = client.get("/api/partitions").json()[0]
    assert partitions["consumed"] == 2
    assert partitions["available"] == 1


def test_remove_members_rejects_a_shaft_not_in_the_set(client):
    _, ids_a = _make_batch_with_measured_shafts(client, 19, 1)
    _, ids_b = _make_batch_with_measured_shafts(client, 20, 1)
    created = client.post(
        "/api/sets", json={"name": "Set A", "diameterId": 1, "woodId": 1, "shaftIds": ids_a}
    ).json()

    r = client.post(f"/api/sets/{created['id']}/members:remove", json={"shaftIds": ids_b})
    assert r.status_code == 400


def test_remove_members_rejects_a_disbanded_set(client):
    _, shaft_ids = _make_batch_with_measured_shafts(client, 19, 1)
    created = client.post(
        "/api/sets", json={"name": "Set A", "diameterId": 1, "woodId": 1, "shaftIds": shaft_ids}
    ).json()
    client.delete(f"/api/sets/{created['id']}")

    r = client.post(f"/api/sets/{created['id']}/members:remove", json={"shaftIds": shaft_ids})
    assert r.status_code == 400


def test_get_set_404_for_unknown_id(client):
    r = client.get("/api/sets/999")
    assert r.status_code == 404


def test_create_set_rejects_empty_selection(client):
    r = client.post("/api/sets", json={"name": "Empty", "diameterId": 1, "woodId": 1, "shaftIds": []})
    assert r.status_code == 422

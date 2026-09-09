def _make_batch_with_measured_shafts(client, batch_no, spines, weight="23.50", diameter_id=1, wood_id=1):
    """spines: list of spine strings, one shaft per entry, spine A == spine B
    (so avg_spine_mlb == spine * 1000 exactly)."""
    r = client.post(
        "/api/batches",
        json={
            "batchNo": batch_no,
            "expectedCount": len(spines),
            "diameterId": diameter_id,
            "woodId": wood_id,
        },
    )
    batch_id = r.json()["id"]
    for seq, spine in enumerate(spines, start=1):
        client.patch(
            f"/api/batches/{batch_id}/shafts/{seq}",
            json={"spineA": spine, "spineB": spine, "weight": weight},
        )
    return batch_id


def _default_param_set_id(client):
    params = client.get("/api/params").json()
    return next(p["id"] for p in params if p["isDefault"])


def test_analysis_max_set_finds_the_tightest_window(client):
    # default param set: spineTolMlb=3000 (3.0 lb), weightTolCg=50 (0.5 g).
    _make_batch_with_measured_shafts(client, 19, ["54.0", "55.0", "56.0", "62.0"])
    param_set_id = _default_param_set_id(client)
    client.patch(f"/api/params/{param_set_id}", json={"objective": "MAX_SET"})

    r = client.get(f"/api/analysis?diameterId=1&woodId=1&paramSetId={param_set_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["objective"] == "MAX_SET"
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    labels = {m["label"] for m in group["members"]}
    assert labels == {"19-01", "19-02", "19-03"}
    # 54.0, 55.0, 56.0 -- mean is exact, no rounding to double-check here.
    assert group["avgSpineMeanMlb"] == 55000
    assert group["weightMeanCg"] == 2350  # every shaft measured at the same 23.50g


def test_analysis_max_dozens_needs_a_solver_not_just_the_biggest_window(client):
    # 24 shafts at spine 54.00, 54.01, ... spread across a wide enough
    # range that a single "biggest window" straddle can strand shafts --
    # mirrors tests/test_grouping.py's synthetic 0..23 case, scaled into
    # real spine values. A 12-shaft window spans 11 steps of 0.01 lb (110
    # mlb); the box constraint is a strict "<" (core/grouping.py), so the
    # tolerance must clear that width, not just match it.
    spines = [f"{54 + i * 0.01:.2f}" for i in range(24)]
    _make_batch_with_measured_shafts(client, 19, spines)
    param_set_id = _default_param_set_id(client)
    client.patch(
        f"/api/params/{param_set_id}",
        json={"objective": "MAX_DOZENS", "spineTolMlb": 120, "weightTolCg": 1000, "dozenSize": 12},
    )

    r = client.get(f"/api/analysis?diameterId=1&woodId=1&paramSetId={param_set_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["objective"] == "MAX_DOZENS"
    assert len(body["groups"]) == 2
    all_members = [m["id"] for g in body["groups"] for m in g["members"]]
    assert len(all_members) == len(set(all_members)) == 24
    assert body["unusedShafts"] == []


def test_analysis_in_spec_pool_filter_shrinks_the_candidate_count(client):
    # default spec bounds: 54.000-60.000 lb. One shaft well below floor.
    _make_batch_with_measured_shafts(client, 19, ["50.0", "55.0", "56.0"])
    param_set_id = _default_param_set_id(client)

    r_all = client.get(f"/api/analysis?diameterId=1&woodId=1&paramSetId={param_set_id}&poolFilter=all")
    r_spec = client.get(
        f"/api/analysis?diameterId=1&woodId=1&paramSetId={param_set_id}&poolFilter=in_spec"
    )
    assert r_all.json()["candidateCount"] == 3
    assert r_spec.json()["candidateCount"] == 2


def test_analysis_every_returned_group_actually_satisfies_its_tolerance_box(client):
    _make_batch_with_measured_shafts(client, 19, ["54.0", "54.5", "55.0", "59.0", "59.5", "60.0"])
    param_set_id = _default_param_set_id(client)
    client.patch(f"/api/params/{param_set_id}", json={"objective": "MAX_SET", "spineTolMlb": 1000})

    body = client.get(f"/api/analysis?diameterId=1&woodId=1&paramSetId={param_set_id}").json()
    for group in body["groups"]:
        spines = [m["avgSpineMlb"] for m in group["members"]]
        assert max(spines) - min(spines) <= 1000


def test_analysis_rejects_unknown_partition_or_param_set(client):
    param_set_id = _default_param_set_id(client)
    r = client.get(f"/api/analysis?diameterId=999&woodId=1&paramSetId={param_set_id}")
    assert r.status_code == 404

    r = client.get("/api/analysis?diameterId=1&woodId=1&paramSetId=999")
    assert r.status_code == 404


def test_analysis_rejects_bad_pool_filter(client):
    param_set_id = _default_param_set_id(client)
    r = client.get(f"/api/analysis?diameterId=1&woodId=1&paramSetId={param_set_id}&poolFilter=bogus")
    assert r.status_code == 400


def test_analysis_group_can_be_committed_through_the_existing_set_builder(client):
    _make_batch_with_measured_shafts(client, 19, ["54.0", "55.0", "56.0"])
    param_set_id = _default_param_set_id(client)
    client.patch(f"/api/params/{param_set_id}", json={"objective": "MAX_SET"})

    body = client.get(f"/api/analysis?diameterId=1&woodId=1&paramSetId={param_set_id}").json()
    shaft_ids = [m["id"] for m in body["groups"][0]["members"]]

    r = client.post(
        "/api/sets",
        json={"name": "From analysis", "diameterId": 1, "woodId": 1, "shaftIds": shaft_ids},
    )
    assert r.status_code == 200
    assert r.json()["memberCount"] == len(shaft_ids)

    rerun = client.get(f"/api/analysis?diameterId=1&woodId=1&paramSetId={param_set_id}").json()
    assert rerun["candidateCount"] == 0

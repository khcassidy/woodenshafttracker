def test_get_params_returns_workbook_defaults(client):
    r = client.get("/api/params")
    default = next(p for p in r.json() if p["isDefault"])
    assert default["spineTolMlb"] == 3000
    assert default["weightTolCg"] == 50
    assert default["specMinMlb"] == 54000
    assert default["specMaxMlb"] == 60000


def test_patch_params_updates_only_given_fields(client):
    r = client.patch("/api/params/1", json={"weightTolCg": 40})
    body = r.json()
    assert body["weightTolCg"] == 40
    assert body["spineTolMlb"] == 3000  # untouched


def test_create_params_adds_a_new_named_set_without_touching_the_default(client):
    r = client.post(
        "/api/params",
        json={
            "name": "Loose tolerance",
            "spineTolMlb": 5000,
            "weightTolCg": 100,
            "objective": "MAX_SET",
            "specMinMlb": 50000,
            "specMaxMlb": 62000,
            "abTolCp": 150,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Loose tolerance"
    assert body["spineTolMlb"] == 5000
    assert body["isDefault"] is False
    assert body["dozenSize"] == 12  # schema default
    assert body["minGroupSize"] == 3  # schema default

    sets = client.get("/api/params").json()
    assert len(sets) == 2
    default = next(p for p in sets if p["isDefault"])
    assert default["name"] == "Workbook defaults"  # unchanged


def test_create_params_rejects_a_duplicate_name(client):
    client.post(
        "/api/params",
        json={
            "name": "Workbook defaults",
            "spineTolMlb": 3000,
            "weightTolCg": 50,
            "specMinMlb": 54000,
            "specMaxMlb": 60000,
            "abTolCp": 100,
        },
    )
    r = client.post(
        "/api/params",
        json={
            "name": "Workbook defaults",
            "spineTolMlb": 3000,
            "weightTolCg": 50,
            "specMinMlb": 54000,
            "specMaxMlb": 60000,
            "abTolCp": 100,
        },
    )
    assert r.status_code == 409


def test_make_default_switches_which_set_is_default(client):
    new_set = client.post(
        "/api/params",
        json={
            "name": "Loose tolerance",
            "spineTolMlb": 5000,
            "weightTolCg": 100,
            "specMinMlb": 50000,
            "specMaxMlb": 62000,
            "abTolCp": 150,
        },
    ).json()

    r = client.post(f"/api/params/{new_set['id']}:makeDefault")
    assert r.status_code == 200
    assert r.json()["isDefault"] is True

    sets = client.get("/api/params").json()
    defaults = [p for p in sets if p["isDefault"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == new_set["id"]

    old_default = next(p for p in sets if p["name"] == "Workbook defaults")
    assert old_default["isDefault"] is False


def test_make_default_404_for_unknown_id(client):
    r = client.post("/api/params/999:makeDefault")
    assert r.status_code == 404


def test_patch_params_renames_a_set(client):
    r = client.patch("/api/params/1", json={"name": "Renamed"})
    assert r.json()["name"] == "Renamed"
    assert client.get("/api/params").json()[0]["name"] == "Renamed"


def test_get_entry_rules_matches_seeded_defaults(client):
    r = client.get("/api/config/entry-rules")
    body = r.json()
    assert body["spineStepCp"] == 50
    assert body["grainsPerGram"] == "15.4324"


def test_patch_entry_rules_updates_only_given_fields(client):
    r = client.patch("/api/config/entry-rules", json={"spineStepCp": 25})
    body = r.json()
    assert body["spineStepCp"] == 25
    assert body["weightStepCg"] == 1  # untouched

    r = client.get("/api/config/entry-rules")
    assert r.json()["spineStepCp"] == 25


def test_patch_entry_rules_accepts_grains_per_gram_as_string(client):
    r = client.patch("/api/config/entry-rules", json={"grainsPerGram": "15.4320"})
    assert r.json()["grainsPerGram"] == "15.4320"

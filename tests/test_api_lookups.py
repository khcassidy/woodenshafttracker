def test_list_diameter_options_orders_by_sort_order_not_label(client):
    r = client.get("/api/lookups/diameter")
    labels = [o["label"] for o in r.json()]
    # Seeded sort_order: 11/32"=1, 5/16"=2, 23/64"=3, Unknown=999 -- last.
    assert labels == ['11/32"', '5/16"', '23/64"', "Unknown"]


def test_create_wood_option_appends_at_end(client):
    r = client.post("/api/lookups/wood", json={"label": "Birch"})
    assert r.status_code == 201
    created = r.json()

    r = client.get("/api/lookups/wood")
    labels = [o["label"] for o in r.json()]
    assert labels[-2] == "Birch"  # last real entry, before the Unknown sentinel
    assert created["sortOrder"] == max(o["sortOrder"] for o in r.json() if o["label"] != "Unknown")


def test_reorder_rewrites_sort_order(client):
    before = client.get("/api/lookups/wood").json()
    real = [o for o in before if o["label"] != "Unknown"]
    reversed_ids = [o["id"] for o in reversed(real)]

    r = client.put("/api/lookups/wood/order", json={"ids": reversed_ids})
    assert r.status_code == 200
    after = [o["id"] for o in r.json() if o["label"] != "Unknown"]
    assert after == reversed_ids


def test_patch_lookup_renames_and_toggles_active(client):
    r = client.post("/api/lookups/shop", json={"label": "Old Name"})
    option_id = r.json()["id"]

    r = client.patch(f"/api/lookups/shop/{option_id}", json={"label": "New Name", "isActive": False})
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "New Name"
    assert body["isActive"] is False


def test_unknown_lookup_kind_returns_404(client):
    r = client.get("/api/lookups/bogus")
    assert r.status_code == 404


def test_create_diameter_option_stores_sixty_fourths(client):
    r = client.post("/api/lookups/diameter", json={"label": '9/32"', "sixtyFourths": 18})
    assert r.status_code == 201
    assert r.json()["sixtyFourths"] == 18


def test_patch_diameter_option_updates_sixty_fourths(client):
    r = client.post("/api/lookups/diameter", json={"label": '9/32"', "sixtyFourths": 18})
    option_id = r.json()["id"]
    r = client.patch(f"/api/lookups/diameter/{option_id}", json={"sixtyFourths": 19})
    assert r.status_code == 200
    assert r.json()["sixtyFourths"] == 19
    assert r.json()["label"] == '9/32"'  # untouched


def test_patch_shop_updates_url_and_notes(client):
    r = client.post("/api/lookups/shop", json={"label": "Bearpaw"})
    option_id = r.json()["id"]
    r = client.patch(
        f"/api/lookups/shop/{option_id}",
        json={"url": "https://example.com", "notes": "good service"},
    )
    assert r.status_code == 200
    assert r.json()["url"] == "https://example.com"
    assert r.json()["notes"] == "good service"


def test_patch_wood_rejects_sixty_fourths_field(client):
    r = client.post("/api/lookups/wood", json={"label": "Maple"})
    option_id = r.json()["id"]
    r = client.patch(f"/api/lookups/wood/{option_id}", json={"sixtyFourths": 20})
    assert r.status_code == 400

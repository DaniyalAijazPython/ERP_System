API = "/api/v1"


def _unit(client, h, code="kg"):
    return next(u["id"] for u in client.get(f"{API}/units", headers=h).json() if u["code"] == code)


def _item(client, h, sku="CL-1", name="Cotton cloth", reorder="0"):
    r = client.post(f"{API}/items", headers=h, json={
        "sku": sku, "name": name, "unit_id": _unit(client, h), "reorder_level": reorder})
    assert r.status_code == 201, r.text
    return r.json()


def _in(client, h, item_id, qty="100", price="450", key=None, **extra):
    headers = dict(h)
    if key:
        headers["Idempotency-Key"] = key
    body = {"lines": [{"item_id": item_id, "quantity": qty, "unit_price": price}], **extra}
    return client.post(f"{API}/stock-in", headers=headers, json=body)


def _stock(client, h, **params):
    return client.get(f"{API}/stock", headers=h, params=params).json()["items"]


def _staff(client, owner_headers, role, email):
    client.post(f"{API}/create_users", headers=owner_headers, json={
        "full_name": "Staff", "email": email, "password": "staff-pass-1", "role": role})
    t = client.post(f"{API}/auth/login", json={"email": email, "password": "staff-pass-1"}).json()
    return {"Authorization": f"Bearer {t['access_token']}"}


def test_stock_in_adds_stock_and_numbers_go_up(client, owner_headers):
    item = _item(client, owner_headers)
    r1 = _in(client, owner_headers, item["id"])
    r2 = _in(client, owner_headers, item["id"], qty="20")
    assert r1.status_code == 201, r1.text
    assert [r1.json()["number"], r2.json()["number"]] == ["GR-0001", "GR-0002"]
    body = r1.json()
    assert body["supplier_name"] == "Local market (cash)"
    assert body["warehouse_name"] == "Main store"
    assert body["payment_method"] == "cash"
    assert body["total"] == "45000.00"
    row = _stock(client, owner_headers)[0]
    assert row["quantity"] == "120.000" and row["unit_code"] == "kg"


def test_average_cost_uses_prices_really_paid(client, owner_headers):
    item = _item(client, owner_headers)
    _in(client, owner_headers, item["id"], qty="100", price="450")
    _in(client, owner_headers, item["id"], qty="100", price="550")
    row = _stock(client, owner_headers)[0]
    assert row["avg_cost"] == "500.0000"
    assert row["stock_value"] == "100000.00"


def test_optional_invoice_fields_and_payment_method(client, owner_headers):
    item = _item(client, owner_headers)
    r = _in(client, owner_headers, item["id"], payment_method="credit",
            supplier_invoice_no="INV-77", tax_amount="500", note="Truck came late")
    b = r.json()
    assert (b["payment_method"], b["supplier_invoice_no"], b["tax_amount"]) == ("credit", "INV-77", "500.00")


def test_same_request_twice_does_not_double_stock(client, owner_headers):
    item = _item(client, owner_headers)
    a = _in(client, owner_headers, item["id"], key="abc-123")
    b = _in(client, owner_headers, item["id"], key="abc-123")
    assert a.json()["id"] == b.json()["id"]
    assert _stock(client, owner_headers)[0]["quantity"] == "100.000"


def test_bad_numbers_are_rejected(client, owner_headers):
    item = _item(client, owner_headers)
    assert _in(client, owner_headers, item["id"], qty="0").status_code == 422
    assert _in(client, owner_headers, item["id"], qty="-5").status_code == 422
    assert _in(client, owner_headers, item["id"], price="-1").status_code == 422
    assert client.post(f"{API}/stock-in", headers=owner_headers, json={"lines": []}).status_code == 422


def test_unknown_or_switched_off_item(client, owner_headers):
    r = _in(client, owner_headers, "00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ITEM_NOT_FOUND"
    item = _item(client, owner_headers)
    client.patch(f"{API}/items/{item['id']}", headers=owner_headers, json={"is_active": False})
    r = _in(client, owner_headers, item["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "ITEM_OFF"


def test_undo_takes_stock_back_and_cannot_repeat(client, owner_headers):
    item = _item(client, owner_headers)
    rid = _in(client, owner_headers, item["id"]).json()["id"]
    u = client.post(f"{API}/stock-in/{rid}/undo", headers=owner_headers)
    assert u.status_code == 200 and u.json()["status"] == "undone"
    assert _stock(client, owner_headers)[0]["quantity"] == "0.000"
    again = client.post(f"{API}/stock-in/{rid}/undo", headers=owner_headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_UNDONE"


def test_undo_blocked_when_stock_already_used_with_easy_message(client, owner_headers):
    item = _item(client, owner_headers)
    rid = _in(client, owner_headers, item["id"], qty="100").json()["id"]
    client.post(f"{API}/stock-fix", headers=owner_headers,
                json={"item_id": item["id"], "counted_quantity": "40", "reason": "Cloth used in cutting"})
    r = client.post(f"{API}/stock-in/{rid}/undo", headers=owner_headers)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "NOT_ENOUGH_STOCK"
    assert err["message"] == "Not enough Cotton cloth: you have 40 kg, you need 100 kg"


def test_fix_count_changes_stock_and_needs_a_reason(client, owner_headers):
    item = _item(client, owner_headers)
    _in(client, owner_headers, item["id"], qty="100")
    r = client.post(f"{API}/stock-fix", headers=owner_headers,
                    json={"item_id": item["id"], "counted_quantity": "92.5", "reason": "Counted by hand"})
    assert r.status_code == 201, r.text
    assert r.json()["quantity"] == "-7.500" and r.json()["kind"] == "count_fix"
    assert _stock(client, owner_headers)[0]["quantity"] == "92.500"
    assert client.post(f"{API}/stock-fix", headers=owner_headers,
                       json={"item_id": item["id"], "counted_quantity": "10", "reason": ""}).status_code == 422
    same = client.post(f"{API}/stock-fix", headers=owner_headers,
                       json={"item_id": item["id"], "counted_quantity": "92.5", "reason": "Check again"})
    assert same.status_code == 409 and same.json()["error"]["code"] == "COUNT_IS_SAME"


def test_stock_history_newest_first_and_never_deleted(client, owner_headers):
    item = _item(client, owner_headers)
    rid = _in(client, owner_headers, item["id"]).json()["id"]
    client.post(f"{API}/stock-fix", headers=owner_headers,
                json={"item_id": item["id"], "counted_quantity": "110", "reason": "Found extra rolls"})
    client.post(f"{API}/stock-in/{rid}/undo", headers=owner_headers)
    hist = client.get(f"{API}/stock-history", headers=owner_headers).json()
    assert [h["kind"] for h in hist] == ["stock_in_undone", "count_fix", "stock_in"]
    assert hist[0]["reference_number"] == "GR-0001"
    shelf = float(_stock(client, owner_headers)[0]["quantity"])
    assert shelf == 10 and sum(float(h["quantity"]) for h in hist) == shelf  # history adds up to the shelf
    only = client.get(f"{API}/stock-history", headers=owner_headers, params={"item_id": item["id"]}).json()
    assert len(only) == 3


def test_low_stock_filter(client, owner_headers):
    a = _item(client, owner_headers, sku="A", name="Thread", reorder="50")
    b = _item(client, owner_headers, sku="B", name="Buttons", reorder="10")
    _in(client, owner_headers, a["id"], qty="30")
    _in(client, owner_headers, b["id"], qty="500")
    low = _stock(client, owner_headers, low_only=True)
    assert [r["name"] for r in low] == ["Thread"] and low[0]["is_low"] is True
    assert len(_stock(client, owner_headers)) == 2


def test_stock_per_warehouse(client, owner_headers):
    item = _item(client, owner_headers)
    second = client.post(f"{API}/warehouses", headers=owner_headers, json={"name": "Factory floor"}).json()
    _in(client, owner_headers, item["id"], qty="100")
    _in(client, owner_headers, item["id"], qty="30", warehouse_id=second["id"])
    assert _stock(client, owner_headers)[0]["quantity"] == "130.000"
    assert _stock(client, owner_headers, warehouse_id=second["id"])[0]["quantity"] == "30.000"


def test_switched_off_warehouse_rejected(client, owner_headers):
    item = _item(client, owner_headers)
    second = client.post(f"{API}/warehouses", headers=owner_headers, json={"name": "Old shed"}).json()
    client.patch(f"{API}/warehouses/{second['id']}", headers=owner_headers, json={"is_active": False})
    r = _in(client, owner_headers, item["id"], warehouse_id=second["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "WAREHOUSE_OFF"


def test_who_can_do_what(client, owner_headers):
    item = _item(client, owner_headers)
    viewer = _staff(client, owner_headers, "viewer", "v@example.com")
    store = _staff(client, owner_headers, "store", "s@example.com")
    sales = _staff(client, owner_headers, "sales", "sa@example.com")
    assert _in(client, viewer, item["id"]).status_code == 403
    assert _in(client, sales, item["id"]).status_code == 403
    assert _in(client, store, item["id"]).status_code == 201
    assert client.get(f"{API}/stock", headers=viewer).status_code == 200
    assert client.get(f"{API}/stock-history", headers=viewer).status_code == 200
    assert client.post(f"{API}/stock-fix", headers=viewer, json={
        "item_id": item["id"], "counted_quantity": "1", "reason": "test"}).status_code == 403


def test_companies_cannot_see_each_others_stock(client, owner_headers):
    item = _item(client, owner_headers)
    rid = _in(client, owner_headers, item["id"]).json()["id"]
    other = client.post(f"{API}/auth/register-company", json={
        "company_name": "Lahore Textiles", "full_name": "Bilal", "email": "bilal@example.com",
        "password": "another-pass-1"}).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"{API}/stock-in/{rid}", headers=oh).status_code == 404
    assert client.post(f"{API}/stock-in/{rid}/undo", headers=oh).status_code == 404
    assert client.get(f"{API}/stock-in", headers=oh).json() == []
    assert client.get(f"{API}/stock-history", headers=oh).json() == []
    assert _in(client, oh, item["id"]).status_code == 404
    # their numbering starts again at 1
    mine = _item(client, oh, sku="X", name="Their item")
    assert _in(client, oh, mine["id"]).json()["number"] == "GR-0001"

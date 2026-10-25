import pytest

API = "/api/v1"


def _headers(client, owner_headers, role, email):
    r = client.post(
        f"{API}/create_users",
        headers=owner_headers,
        json={"full_name": "Staff Person", "email": email, "password": "staff-pass-1", "role": role},
    )
    assert r.status_code == 201, r.text
    login = client.post(f"{API}/auth/login", json={"email": email, "password": "staff-pass-1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _unit_id(client, headers, code="kg"):
    units = client.get(f"{API}/units", headers=headers).json()
    return next(u["id"] for u in units if u["code"] == code)


def _item(client, headers, **over):
    body = {"sku": "cl-001", "name": "Cotton cloth", "item_type": "raw_material",
            "unit_id": _unit_id(client, headers), "reorder_level": "50"}
    body.update(over)
    return client.post(f"{API}/items", headers=headers, json=body)


def test_new_company_gets_starter_data(client, owner_headers):
    codes = {u["code"] for u in client.get(f"{API}/units", headers=owner_headers).json()}
    assert {"pcs", "kg", "m"} <= codes
    whs = client.get(f"{API}/warehouses", headers=owner_headers).json()
    assert [(w["name"], w["is_default"]) for w in whs] == [("Main store", True)]
    sup = client.get(f"{API}/suppliers", headers=owner_headers).json()
    assert [(s["name"], s["is_system"]) for s in sup] == [("Local market (cash)", True)]


def test_item_create_normalizes_and_rejects_duplicate_sku(client, owner_headers):
    r = _item(client, owner_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sku"] == "CL-001"
    assert body["unit"]["code"] == "kg"
    assert body["reorder_level"] == "50.000"

    dup = _item(client, owner_headers, sku="cl-001", name="Other")
    assert dup.status_code == 409
    assert dup.json()["error"] == {
        "code": "SKU_EXISTS", "message": "Item code 'CL-001' is already used", "field": "sku"}


def test_item_list_search_and_pagination(client, owner_headers):
    for i in range(5):
        assert _item(client, owner_headers, sku=f"S{i}", name=f"Thread {i}").status_code == 201
    _item(client, owner_headers, sku="BTN", name="Button")
    page = client.get(f"{API}/items", headers=owner_headers, params={"q": "thread", "limit": 2}).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    page2 = client.get(f"{API}/items", headers=owner_headers, params={"q": "thread", "limit": 2, "offset": 4}).json()
    assert len(page2["items"]) == 1


def test_item_update_and_deactivate_hides_from_default_list(client, owner_headers):
    item = _item(client, owner_headers).json()
    r = client.patch(f"{API}/items/{item['id']}", headers=owner_headers,
                     json={"name": "Cotton cloth (white)", "is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get(f"{API}/items", headers=owner_headers).json()["total"] == 0
    assert client.get(f"{API}/items", headers=owner_headers, params={"include_inactive": True}).json()["total"] == 1


def test_negative_reorder_level_rejected(client, owner_headers):
    assert _item(client, owner_headers, reorder_level="-1").status_code == 422


def test_unknown_unit_rejected(client, owner_headers):
    r = _item(client, owner_headers, unit_id="00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "UNIT_NOT_FOUND"


def test_roles_viewer_reads_but_cannot_write(client, owner_headers):
    viewer = _headers(client, owner_headers, "viewer", "v@example.com")
    assert client.get(f"{API}/items", headers=viewer).status_code == 200
    assert _item(client, viewer).status_code == 403


def test_store_can_write_items_but_not_customers(client, owner_headers):
    store = _headers(client, owner_headers, "store", "s@example.com")
    assert _item(client, store).status_code == 201
    assert client.post(f"{API}/customers", headers=store, json={"name": "Ali Traders"}).status_code == 403
    assert client.post(f"{API}/suppliers", headers=store, json={"name": "Raza Mills"}).status_code == 201


def test_sales_can_write_customers(client, owner_headers):
    sales = _headers(client, owner_headers, "sales", "sa@example.com")
    r = client.post(f"{API}/customers", headers=sales, json={"name": "Ali Traders", "phone": "0300-1234567"})
    assert r.status_code == 201 and r.json()["kind"] == "customer"


def test_supplier_and_customer_namespaces_are_separate(client, owner_headers):
    assert client.post(f"{API}/suppliers", headers=owner_headers, json={"name": "Same Name"}).status_code == 201
    assert client.post(f"{API}/customers", headers=owner_headers, json={"name": "Same Name"}).status_code == 201
    dup = client.post(f"{API}/suppliers", headers=owner_headers, json={"name": "Same Name"})
    assert dup.status_code == 409
    assert len(client.get(f"{API}/customers", headers=owner_headers).json()) == 1


def test_builtin_cash_supplier_is_protected(client, owner_headers):
    sup = client.get(f"{API}/suppliers", headers=owner_headers).json()[0]
    r = client.patch(f"{API}/suppliers/{sup['id']}", headers=owner_headers, json={"is_active": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SYSTEM_RECORD"


def test_default_warehouse_switching_and_protection(client, owner_headers):
    main = client.get(f"{API}/warehouses", headers=owner_headers).json()[0]
    new = client.post(f"{API}/warehouses", headers=owner_headers, json={"name": "Factory floor"}).json()
    # cannot switch off the current default
    r = client.patch(f"{API}/warehouses/{main['id']}", headers=owner_headers, json={"is_active": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DEFAULT_REQUIRED"
    # making another one default moves the flag
    client.patch(f"{API}/warehouses/{new['id']}", headers=owner_headers, json={"is_default": True})
    flags = {w["name"]: w["is_default"] for w in client.get(f"{API}/warehouses", headers=owner_headers).json()}
    assert flags == {"Main store": False, "Factory floor": True}


def test_tenants_cannot_see_each_others_data(client, owner_headers):
    item = _item(client, owner_headers).json()
    other = client.post(f"{API}/auth/register-company", json={
        "company_name": "Lahore Textiles", "full_name": "Bilal", "email": "bilal@example.com",
        "password": "another-pass-1"}).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"{API}/items", headers=oh).json()["total"] == 0
    assert client.get(f"{API}/items/{item['id']}", headers=oh).status_code == 404
    assert client.patch(f"{API}/items/{item['id']}", headers=oh, json={"name": "hijack"}).status_code == 404
    # and cannot attach another company's unit to its own item
    r = _item(client, oh, unit_id=item["unit_id"], sku="X1")
    assert r.status_code == 404

from decimal import Decimal

from tests.test_stock import API, _in, _staff, _stock

D = Decimal


def _make_item(client, h, sku, name, unit="pcs"):
    uid = next(u["id"] for u in client.get(f"{API}/units", headers=h).json() if u["code"] == unit)
    r = client.post(f"{API}/items", headers=h, json={"sku": sku, "name": name, "unit_id": uid})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _setup(client, h, cloth_qty="400", cloth_price="100", thread_qty="200", thread_price="10"):
    """Shirt = 2 m cloth + 1 spool thread. Stock: cloth and thread."""
    cloth = _make_item(client, h, "CLOTH", "Cloth", "m")
    thread = _make_item(client, h, "THREAD", "Thread", "pcs")
    shirt = _make_item(client, h, "SHIRT", "Shirt", "pcs")
    _in(client, h, cloth, qty=cloth_qty, price=cloth_price)
    _in(client, h, thread, qty=thread_qty, price=thread_price)
    r = client.post(f"{API}/recipes", headers=h, json={
        "item_id": shirt, "lines": [{"item_id": cloth, "quantity": "2"}, {"item_id": thread, "quantity": "1"}]})
    assert r.status_code == 201, r.text
    return {"cloth": cloth, "thread": thread, "shirt": shirt, "recipe": r.json()["id"]}


def _make(client, h, recipe, qty="100", key=None, **extra):
    headers = dict(h)
    if key:
        headers["Idempotency-Key"] = key
    return client.post(f"{API}/production", headers=headers, json={"recipe_id": recipe, "quantity": qty, **extra})


def _qty(client, h, name):
    return next(r["quantity"] for r in _stock(client, h) if r["name"] == name)


# ------------------------------------------------------------ Recipe
def test_create_recipe_and_read_it(client, owner_headers):
    s = _setup(client, owner_headers)
    r = client.get(f"{API}/recipes/{s['recipe']}", headers=owner_headers).json()
    assert r["item_name"] == "Shirt" and D(r["makes"]) == 1
    assert [(l["item_name"], l["unit_code"], D(l["quantity"])) for l in r["lines"]] == [
        ("Cloth", "m", 2), ("Thread", "pcs", 1)]
    assert len(client.get(f"{API}/recipes", headers=owner_headers).json()) == 1


def test_recipe_rules(client, owner_headers):
    s = _setup(client, owner_headers)
    dup = client.post(f"{API}/recipes", headers=owner_headers,
                      json={"item_id": s["shirt"], "lines": [{"item_id": s["cloth"], "quantity": "1"}]})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "RECIPE_EXISTS"
    other = _make_item(client, owner_headers, "SOCK", "Sock")
    self_use = client.post(f"{API}/recipes", headers=owner_headers,
                           json={"item_id": other, "lines": [{"item_id": other, "quantity": "1"}]})
    assert self_use.status_code == 409 and self_use.json()["error"]["code"] == "SAME_ITEM"
    twice = client.post(f"{API}/recipes", headers=owner_headers, json={"item_id": other, "lines": [
        {"item_id": s["cloth"], "quantity": "1"}, {"item_id": s["cloth"], "quantity": "2"}]})
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "DUPLICATE_MATERIAL"
    zero = client.post(f"{API}/recipes", headers=owner_headers,
                       json={"item_id": other, "lines": [{"item_id": s["cloth"], "quantity": "0"}]})
    assert zero.status_code == 422
    nothing = client.post(f"{API}/recipes", headers=owner_headers, json={"item_id": other, "lines": []})
    assert nothing.status_code == 422
    ghost = client.post(f"{API}/recipes", headers=owner_headers, json={
        "item_id": other, "lines": [{"item_id": "00000000-0000-0000-0000-000000000000", "quantity": "1"}]})
    assert ghost.status_code == 404 and ghost.json()["error"]["code"] == "ITEM_NOT_FOUND"


def test_change_recipe_lines_and_switch_off(client, owner_headers):
    s = _setup(client, owner_headers)
    r = client.patch(f"{API}/recipes/{s['recipe']}", headers=owner_headers,
                     json={"lines": [{"item_id": s["cloth"], "quantity": "3"}]})
    assert r.status_code == 200 and len(r.json()["lines"]) == 1 and D(r.json()["lines"][0]["quantity"]) == 3
    off = client.patch(f"{API}/recipes/{s['recipe']}", headers=owner_headers, json={"is_active": False})
    assert off.json()["is_active"] is False
    assert client.get(f"{API}/recipes", headers=owner_headers).json() == []
    blocked = _make(client, owner_headers, s["recipe"], qty="1")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "RECIPE_OFF"


# ------------------------------------------------------------ Can I make this?
def test_can_i_make_this(client, owner_headers):
    s = _setup(client, owner_headers, cloth_qty="150")
    url = f"{API}/recipes/{s['recipe']}/check"
    ok = client.get(url, headers=owner_headers, params={"quantity": "50"}).json()
    assert ok["can_make"] is True and D(ok["est_unit_cost"]) == 210      # 2 x 100 + 1 x 10
    no = client.get(url, headers=owner_headers, params={"quantity": "100"}).json()
    assert no["can_make"] is False
    cloth = next(l for l in no["lines"] if l["item_name"] == "Cloth")
    assert (D(cloth["needed"]), D(cloth["have"]), D(cloth["short"]), cloth["ok"]) == (200, 150, 50, False)
    assert client.get(url, headers=owner_headers, params={"quantity": "0"}).status_code == 422


# ------------------------------------------------------------ Make
def test_make_items_moves_stock_and_works_out_cost(client, owner_headers):
    s = _setup(client, owner_headers)           # cloth 400 @ 100, thread 200 @ 10
    r = _make(client, owner_headers, s["recipe"], qty="100",
              extra_costs=[{"name": "Stitching labour", "amount": "5000"}])
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["number"] == "PD-0001" and b["status"] == "done" and b["item_name"] == "Shirt"
    assert D(b["materials_cost"]) == 21000      # 200 m x 100 + 100 pcs x 10
    assert D(b["extra_cost"]) == 5000 and D(b["total_cost"]) == 26000
    assert D(b["unit_cost"]) == 260
    assert [(m["item_name"], D(m["quantity"]), D(m["unit_cost"])) for m in b["materials"]] == [
        ("Cloth", 200, 100), ("Thread", 100, 10)]
    assert b["extra_costs"][0]["name"] == "Stitching labour"
    assert D(_qty(client, owner_headers, "Cloth")) == 200
    assert D(_qty(client, owner_headers, "Thread")) == 100
    shirt = next(x for x in _stock(client, owner_headers) if x["name"] == "Shirt")
    assert D(shirt["quantity"]) == 100 and D(shirt["avg_cost"]) == 260


def test_new_batch_blends_the_cost(client, owner_headers):
    s = _setup(client, owner_headers)
    _make(client, owner_headers, s["recipe"], qty="100")            # 100 shirts @ 210
    _in(client, owner_headers, s["cloth"], qty="200", price="200")  # cloth now costs more
    _make(client, owner_headers, s["recipe"], qty="50")
    shirt = next(x for x in _stock(client, owner_headers) if x["name"] == "Shirt")
    assert D(shirt["quantity"]) == 150
    assert D(shirt["avg_cost"]) > 210       # second batch cost more, so the average went up


def test_recipe_that_makes_ten_scales_correctly(client, owner_headers):
    cloth = _make_item(client, owner_headers, "C", "Cloth", "m")
    box = _make_item(client, owner_headers, "B", "Cap", "pcs")
    _in(client, owner_headers, cloth, qty="100", price="50")
    rid = client.post(f"{API}/recipes", headers=owner_headers, json={
        "item_id": box, "makes": "10", "lines": [{"item_id": cloth, "quantity": "7.5"}]}).json()["id"]
    r = _make(client, owner_headers, rid, qty="4").json()          # 4 caps need 3 m
    assert D(r["materials"][0]["quantity"]) == 3 and D(r["unit_cost"]) == D("37.5")
    assert D(_qty(client, owner_headers, "Cloth")) == 97


def test_not_enough_material_lists_everything_short_and_changes_nothing(client, owner_headers):
    s = _setup(client, owner_headers, cloth_qty="150", thread_qty="40")
    r = _make(client, owner_headers, s["recipe"], qty="100")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "NOT_ENOUGH_MATERIAL"
    assert err["message"] == ("You cannot make 100 Shirt yet. Short: "
                              "Cloth (need 200 m, have 150 m); Thread (need 100 pcs, have 40 pcs)")
    assert D(_qty(client, owner_headers, "Cloth")) == 150 and D(_qty(client, owner_headers, "Thread")) == 40
    assert client.get(f"{API}/production", headers=owner_headers).json() == []


def test_make_same_request_twice(client, owner_headers):
    s = _setup(client, owner_headers)
    a = _make(client, owner_headers, s["recipe"], qty="10", key="m-1")
    b = _make(client, owner_headers, s["recipe"], qty="10", key="m-1")
    assert a.json()["id"] == b.json()["id"]
    assert D(_qty(client, owner_headers, "Shirt")) == 10


def test_materials_and_finished_items_in_different_warehouses(client, owner_headers):
    s = _setup(client, owner_headers)
    floor = client.post(f"{API}/warehouses", headers=owner_headers, json={"name": "Finished goods"}).json()["id"]
    r = _make(client, owner_headers, s["recipe"], qty="10", output_warehouse_id=floor)
    assert r.status_code == 201
    assert r.json()["output_warehouse_name"] == "Finished goods" and r.json()["materials_warehouse_name"] == "Main store"
    in_floor = _stock(client, owner_headers, warehouse_id=floor)
    assert [(x["name"], D(x["quantity"])) for x in in_floor if D(x["quantity"]) > 0] == [("Shirt", 10)]


# ------------------------------------------------------------ Undo
def test_undo_production_puts_everything_back(client, owner_headers):
    s = _setup(client, owner_headers)
    oid = _make(client, owner_headers, s["recipe"], qty="100").json()["id"]
    u = client.post(f"{API}/production/{oid}/undo", headers=owner_headers)
    assert u.status_code == 200 and u.json()["status"] == "undone"
    assert D(_qty(client, owner_headers, "Cloth")) == 400 and D(_qty(client, owner_headers, "Thread")) == 200
    assert D(_qty(client, owner_headers, "Shirt")) == 0
    cloth = next(x for x in _stock(client, owner_headers) if x["name"] == "Cloth")
    assert D(cloth["avg_cost"]) == 100            # cost came back as it was
    again = client.post(f"{API}/production/{oid}/undo", headers=owner_headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_UNDONE"


def test_cannot_undo_when_shirts_are_already_used(client, owner_headers):
    s = _setup(client, owner_headers)
    oid = _make(client, owner_headers, s["recipe"], qty="100").json()["id"]
    client.post(f"{API}/stock-out", headers=owner_headers, json={
        "reason": "sample", "lines": [{"item_id": s["shirt"], "quantity": "60"}]})
    r = client.post(f"{API}/production/{oid}/undo", headers=owner_headers)
    assert r.status_code == 409
    assert r.json()["error"]["message"] == "Not enough Shirt: you have 40 pcs, you need 100 pcs"
    assert D(_qty(client, owner_headers, "Cloth")) == 200       # nothing was put back
    assert client.get(f"{API}/production/{oid}", headers=owner_headers).json()["status"] == "done"


# ------------------------------------------------------------ People and companies
def test_who_can_do_what(client, owner_headers):
    s = _setup(client, owner_headers)
    prod = _staff(client, owner_headers, "production", "p@example.com")
    store = _staff(client, owner_headers, "store", "st@example.com")
    sales = _staff(client, owner_headers, "sales", "sa@example.com")
    viewer = _staff(client, owner_headers, "viewer", "v@example.com")
    assert _make(client, sales, s["recipe"], qty="1").status_code == 403
    assert _make(client, viewer, s["recipe"], qty="1").status_code == 403
    assert _make(client, store, s["recipe"], qty="1").status_code == 201
    assert _make(client, prod, s["recipe"], qty="1").status_code == 201
    # recipes: production and managers write, store keepers only look
    body = {"item_id": s["cloth"], "lines": [{"item_id": s["thread"], "quantity": "1"}]}
    assert client.post(f"{API}/recipes", headers=store, json=body).status_code == 403
    assert client.post(f"{API}/recipes", headers=prod, json=body).status_code == 201
    assert client.get(f"{API}/recipes", headers=viewer).status_code == 200
    assert client.get(f"{API}/production", headers=viewer).status_code == 200


def test_companies_cannot_see_each_others_recipes_or_production(client, owner_headers):
    s = _setup(client, owner_headers)
    oid = _make(client, owner_headers, s["recipe"], qty="10").json()["id"]
    other = client.post(f"{API}/auth/register-company", json={
        "company_name": "Lahore Textiles", "full_name": "Bilal", "email": "bilal@example.com",
        "password": "another-pass-1"}).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"{API}/recipes", headers=oh).json() == []
    assert client.get(f"{API}/recipes/{s['recipe']}", headers=oh).status_code == 404
    assert client.get(f"{API}/recipes/{s['recipe']}/check", headers=oh, params={"quantity": "1"}).status_code == 404
    assert _make(client, oh, s["recipe"], qty="1").status_code == 404
    assert client.get(f"{API}/production/{oid}", headers=oh).status_code == 404
    assert client.post(f"{API}/production/{oid}/undo", headers=oh).status_code == 404

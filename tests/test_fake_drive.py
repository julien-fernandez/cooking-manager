"""Le faux drive tient le contrat REST du connecteur : la version publique tourne sans enseigne."""
import json

from fastapi.testclient import TestClient

from backend.fake_drive import create_app


def client(tmp_path):
    return TestClient(create_app(tmp_path / "cart.json"))


def test_health_says_authenticated(tmp_path):
    assert client(tmp_path).get("/health").json()["authenticated"] is True


def test_search_returns_offers_for_the_food_name(tmp_path):
    results = client(tmp_path).post("/search", json={"query": "farine", "limit": 3}).json()["results"]
    assert results and all("farine" in r["name"].lower() for r in results)
    assert len(results) <= 3


def test_add_then_set_quantity_is_written_to_file(tmp_path):
    c = client(tmp_path)
    offer = c.post("/search", json={"query": "riz"}).json()["results"][0]
    item = {k: offer[k] for k in ("product_id", "offer_id", "seller_id")}
    c.post("/cart/items", json={**item, "quantity": 2})
    lines = c.get("/cart").json()["lines"]
    assert [(line["offer_id"], line["quantity"]) for line in lines] == [(offer["offer_id"], 2)]
    c.post("/cart/items/remove", json={**item, "quantity": 0})
    assert c.get("/cart").json()["lines"] == []
    assert json.loads((tmp_path / "cart.json").read_text())["lines"] == []


def test_add_replaces_quantity_like_the_real_drive(tmp_path):
    c = client(tmp_path)
    offer = c.post("/search", json={"query": "riz"}).json()["results"][0]
    item = {k: offer[k] for k in ("product_id", "offer_id", "seller_id")}
    c.post("/cart/items", json={**item, "quantity": 2})
    c.post("/cart/items", json={**item, "quantity": 3})
    assert c.get("/cart").json()["lines"][0]["quantity"] == 3


def test_order_empties_the_cart(tmp_path):
    c = client(tmp_path)
    offer = c.post("/search", json={"query": "riz"}).json()["results"][0]
    c.post("/cart/items", json={**{k: offer[k] for k in ("product_id", "offer_id", "seller_id")}, "quantity": 1})
    order = c.post("/order").json()
    assert order["status"] == "created" and order["lines"][0]["quantity"] == 1
    assert c.get("/cart").json()["lines"] == []

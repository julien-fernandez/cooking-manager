"""Faux drive : tient le contrat REST du connecteur d'enseigne, panier en mémoire écrit dans un fichier JSON.

Les connecteurs réels dépendent d'API non documentées et restent privés. Celui-ci permet de faire
tourner l'application de bout en bout : `uvicorn backend.fake_drive:app --port 8120`, puis
`DRIVE_A_REST_URL=http://127.0.0.1:8120`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

CATALOGUE = [
    "Farine de blé T55 1 kg", "Farine complète T150 1 kg", "Riz basmati 1 kg", "Riz rond 500 g",
    "Tomates pelées 400 g", "Pois chiches 400 g", "Lentilles vertes 500 g", "Huile d'olive 1 L",
    "Oignons jaunes 1 kg", "Pommes de terre 2,5 kg", "Thon au naturel 3x80 g", "Œufs x12",
]


class SearchBody(BaseModel):
    query: str
    limit: int = 10


class ItemBody(BaseModel):
    product_id: str
    offer_id: str
    quantity: int
    seller_id: str | None = None


class CartIdBody(BaseModel):
    cart_id: str


def _offer(index: int, name: str) -> dict:
    return {"name": name, "product_id": f"p{index}", "offer_id": f"o{index}",
            "drive_a_id": f"p{index}", "brand": None, "seller_id": "demo", "stock": 50}


def create_app(cart_file: Path) -> FastAPI:
    app = FastAPI(title="fake drive")
    lines: list[dict] = []

    def save() -> None:
        cart_file.parent.mkdir(parents=True, exist_ok=True)
        cart_file.write_text(json.dumps({"lines": lines}, ensure_ascii=False, indent=2))

    @app.get("/health")
    def health() -> dict:
        return {"authenticated": True, "store": "fake"}

    @app.post("/search")
    def search(body: SearchBody) -> dict:
        words = body.query.lower().split()
        hits = [_offer(i, n) for i, n in enumerate(CATALOGUE) if all(w in n.lower() for w in words)]
        return {"results": hits[: body.limit]}

    @app.get("/cart")
    def cart() -> dict:
        return {"cart_id": "demo", "lines": lines}

    @app.post("/cart/id")
    def pin(body: CartIdBody) -> dict:
        return {"cart_id": body.cart_id}

    def put(body: ItemBody) -> dict:
        # Comme le drive réel, l'ajout REMPLACE la quantité d'une offre déjà au panier.
        lines[:] = [line for line in lines if line["offer_id"] != body.offer_id]
        if body.quantity > 0:
            lines.append(body.model_dump())
        save()
        return {"lines": lines}

    app.post("/cart/items")(put)
    app.post("/cart/items/remove")(put)

    @app.post("/order")
    def order() -> dict:
        placed = {"status": "created", "lines": list(lines)}
        lines.clear()
        save()
        return placed

    return app


app = create_app(Path(os.environ.get("FAKE_DRIVE_CART", "fake-drive-cart.json")))

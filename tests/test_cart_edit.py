"""Retirer une ligne ou fixer sa quantité : chez Drive A d'abord, relu, puis tracé (#175)."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from backend import app as app_module
from backend import drive_a


class TestPushTarget:
    def test_un_produit_deja_au_panier_recoit_le_total(self):
        assert drive_a.push_target(2, 1) == 3

    def test_ajout_confirme(self):
        assert drive_a.push_error(2, 3, 3) is None

    def test_ajout_remplace_au_lieu_d_ajouter_se_dit(self):
        """Le piège du 05/10 : POST /cart/items remplaçait 2 par 1."""
        assert "rien changé" in (drive_a.push_error(2, 3, 1) or "")

    def test_plafond_silencieux_se_dit(self):
        """Œufs demandés ×3, facturés ×2 : max_quantity plafonne sans erreur."""
        assert drive_a.push_error(0, 3, 2) == (
            "le drive porte 2 exemplaire(s) au lieu de 3 : quantité plafonnée")


class TestEditTarget:
    def test_retirer_la_seule_ligne(self):
        assert drive_a.edit_target(2, 2, 0) == 0

    def test_retirer_laisse_les_exemplaires_d_une_autre_ligne(self):
        assert drive_a.edit_target(3, 2, 0) == 1

    def test_corriger_une_quantite(self):
        assert drive_a.edit_target(3, 3, 1) == 1

    def test_jamais_sous_zero(self):
        assert drive_a.edit_target(0, 2, 0) == 0


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    async def fetchrow(self, sql, item_id):
        row = self.rows.get(item_id)
        return dict(row) if row else None

    async def execute(self, sql, item_id, *args):
        row = self.rows[item_id]
        if "status = 'skipped'" in sql:
            row["status"], row["reason"] = "skipped", args[0] + row["reason"]
        else:
            row["quantity"], row["reason"] = args[0], args[1] + row["reason"]


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


class FakeDrive:
    def __init__(self, in_cart: int, follows: bool = True, authenticated: bool = True):
        self.in_cart, self.follows, self.authenticated = in_cart, follows, authenticated
        self.set_calls = []

    async def session_status(self):
        return {"authenticated": self.authenticated}

    async def get_cart(self):
        return {"items": [{"offer_id": "o1", "quantity": self.in_cart}]}

    async def set_quantity(self, offer, quantity):
        self.set_calls.append(quantity)
        if self.follows:
            self.in_cart = quantity
        return {}


def line(status="pushed", quantity=2):
    return {"id": 7, "status": status, "quantity": quantity, "reason": "élu",
            "product_name": "Courgettes 1 kg", "requested": "courgette",
            "product_id": "p1", "offer_id": "o1", "drive_a_id": None, "seller_id": None}


@pytest.fixture
def setup(monkeypatch):
    def make(row, drive):
        rows = {7: row}
        async def get_pool(dsn):
            return FakePool(FakeConn(rows))
        monkeypatch.setattr(app_module, "get_pool", get_pool)
        for name in ("session_status", "get_cart", "set_quantity"):
            monkeypatch.setattr(drive_a, name, getattr(drive, name))
        return rows
    return make


def edit(quantity, reason="trop de courgettes"):
    return asyncio.run(app_module._edit_cart_line(7, quantity, reason))


def test_les_deux_routes_sont_declarees():
    routes = {(getattr(r, "path", ""), m) for r in app_module.app.routes
              for m in getattr(r, "methods", ())}
    assert ("/api/cart/items/{item_id}", "PATCH") in routes
    assert ("/api/cart/items/{item_id}", "DELETE") in routes


def test_retirer_une_ligne_poussee(setup):
    drive = FakeDrive(in_cart=2)
    rows = setup(line(), drive)
    result = edit(0)
    assert drive.set_calls == [0]
    assert result["drive"] == {"before": 2, "after": 0}
    assert rows[7]["status"] == "skipped"
    assert rows[7]["reason"] == "retirée (trop de courgettes) · élu"


def test_corriger_la_quantite(setup):
    drive = FakeDrive(in_cart=3)
    rows = setup(line(quantity=3), drive)
    edit(1, "deux suffisent")
    assert drive.set_calls == [1]
    assert (rows[7]["status"], rows[7]["quantity"]) == ("pushed", 1)
    assert rows[7]["reason"].startswith("quantité 3 → 1 (deux suffisent)")


def test_le_drive_qui_ne_suit_pas_laisse_la_table_intacte(setup):
    rows = setup(line(), FakeDrive(in_cart=2, follows=False))
    with pytest.raises(HTTPException) as e:
        edit(0)
    assert e.value.status_code == 409
    assert e.value.detail == {"error": "le drive n'a pas suivi : la ligne reste telle quelle",
                              "before": 2, "wanted": 0, "after": 2}
    assert rows[7]["status"] == "pushed"


def test_session_anonyme_refusee(setup):
    setup(line(), FakeDrive(in_cart=2, authenticated=False))
    with pytest.raises(HTTPException) as e:
        edit(0)
    assert e.value.status_code == 409


def test_ligne_non_poussee_ne_touche_pas_au_drive(setup):
    drive = FakeDrive(in_cart=5)
    rows = setup(line(status="elected"), drive)
    result = edit(0)
    assert drive.set_calls == [] and result["drive"] is None
    assert rows[7]["status"] == "skipped"


@pytest.mark.parametrize("quantity,reason", [(0, "  "), (-1, "motif")])
def test_motif_et_quantite_obligatoires(setup, quantity, reason):
    setup(line(), FakeDrive(in_cart=2))
    with pytest.raises(HTTPException) as e:
        edit(quantity, reason)
    assert e.value.status_code == 422


def test_ligne_deja_ecartee(setup):
    setup(line(status="skipped"), FakeDrive(in_cart=0))
    with pytest.raises(HTTPException) as e:
        edit(0)
    assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_outils_mcp(monkeypatch):
    cooking_mcp = pytest.importorskip("backend.cooking_mcp")
    seen = []

    async def fake_api(method, path, body=None):
        seen.append((method, path, body))
        return {}

    monkeypatch.setattr(cooking_mcp, "_api", fake_api)
    tool = lambda name: getattr(getattr(cooking_mcp, name), "fn", getattr(cooking_mcp, name))  # noqa: E731
    await tool("cart_set_quantity")(7, 1, "deux suffisent")
    await tool("cart_remove")(7, "en trop")
    assert seen == [("PATCH", "/api/cart/items/7", {"quantity": 1, "reason": "deux suffisent"}),
                    ("DELETE", "/api/cart/items/7", {"reason": "en trop"})]

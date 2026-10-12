"""Les quatre transitions demandent leurs gates AVANT tout effet ; verify et order mesurent le gate 9."""

import asyncio
from typing import cast

import pytest
from fastapi import HTTPException

from backend import app as app_module


@pytest.fixture
def gates(monkeypatch):
    calls = []

    async def require_gates(slug, transition, override_reason="", actor="agent"):
        calls.append((slug, transition, override_reason, actor))
        raise HTTPException(409, {"error": "gate", "transition": transition})

    async def no_pool(dsn):
        raise AssertionError("aucun effet ne doit précéder le jugement des gates")

    monkeypatch.setattr(app_module.gate_engine, "require_gates", require_gates)
    monkeypatch.setattr(app_module, "get_pool", no_pool)
    return calls


def test_publier_demande_publish(gates):
    body = app_module.MenuStatusUpdate(status="active", override_reason="", actor="ipad")
    with pytest.raises(HTTPException) as e:
        asyncio.run(app_module.update_menu_status("2026-w41", body))
    assert e.value.status_code == 409
    assert gates == [("2026-w41", "publish", "", "ipad")]


def test_archiver_ne_demande_rien(gates):
    with pytest.raises(AssertionError):
        asyncio.run(app_module.update_menu_status(
            "2026-w41", app_module.MenuStatusUpdate(status="archived")))
    assert gates == []


def test_elire_une_ligne_menu_demande_elect(gates):
    body = app_module.CartLineIn(menu_slug="2026-w41", requested="miel")
    with pytest.raises(HTTPException):
        asyncio.run(app_module.add_cart_item(body))
    assert gates == [("2026-w41", "elect", "", "agent")]


def test_ligne_manuelle_non_gardee_a_l_election(gates):
    body = app_module.CartLineIn(menu_slug="2026-w41", requested="dentifrice", origin="manual")
    with pytest.raises(AssertionError):
        asyncio.run(app_module.add_cart_item(body))
    assert gates == []


def test_pousser_demande_push_avant_la_session(gates, monkeypatch):
    async def session_status():
        raise AssertionError("la session ne se lit qu'après les gates")
    monkeypatch.setattr(app_module.drive_a, "session_status", session_status)
    with pytest.raises(HTTPException):
        asyncio.run(app_module.push_cart(app_module.CartPush(menu_slug="2026-w41")))
    assert gates == [("2026-w41", "push", "", "agent")]


def test_verify_journalise_le_gate_9(monkeypatch):
    seen = []

    async def read_real_cart():
        return None, "session anonyme"

    async def record_verify(slug, payload, actor="agent"):
        seen.append((slug, payload["measured"]))

    monkeypatch.setattr(app_module, "_read_real_cart", read_real_cart)
    monkeypatch.setattr(app_module.gate_engine, "record_verify", record_verify)
    out = asyncio.run(app_module.verify_cart(app_module.CartVerify(menu_slug="2026-w41")))
    assert out["measured"] is False and seen == [("2026-w41", False)]


def test_commander_mesure_puis_demande_order(monkeypatch):
    order = []

    async def read_real_cart():
        return {"items": []}, ""

    async def rows_by_ref(slug):
        return {}

    async def persist(slug, cart, by_ref):
        return {"session_id": 1, "items_persisted": 0}

    async def reconcile(slug, cart):
        return {"measured": True, "ok": True, "reason": "", "per_food": [], "counts": {}}

    async def record_verify(slug, payload, actor="agent"):
        order.append("verify")

    async def require_gates(slug, transition, override_reason="", actor="agent"):
        order.append(transition)
        raise HTTPException(409, {"error": "gate"})

    for name, fn in (("_read_real_cart", read_real_cart), ("_cart_rows_by_ref", rows_by_ref),
                     ("_persist_real_cart", persist), ("_reconcile", reconcile)):
        monkeypatch.setattr(app_module, name, fn)
    monkeypatch.setattr(app_module.gate_engine, "record_verify", record_verify)
    monkeypatch.setattr(app_module.gate_engine, "require_gates", require_gates)
    with pytest.raises(HTTPException):
        asyncio.run(app_module.order_cart(app_module.CartOrder(menu_slug="2026-w41")))
    assert order == ["verify", "order"]


@pytest.mark.parametrize("model,kwargs", [
    ("MenuStatusUpdate", {"status": "active"}),
    ("CartLineIn", {"menu_slug": "s", "requested": "x"}),
    ("CartPush", {"menu_slug": "s"}),
    ("CartOrder", {"menu_slug": "s"}),
])
def test_acteur_inconnu_refuse_par_le_modele(model, kwargs):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        getattr(app_module, model)(**kwargs, actor="robot")


def test_substitution_demande_elect(gates):
    body = app_module.CartLineIn(menu_slug="2026-w41", requested="miel", origin="substitution")
    with pytest.raises(HTTPException):
        asyncio.run(app_module.add_cart_item(body))
    assert gates == [("2026-w41", "elect", "", "agent")]


class _OrderConn:
    def __init__(self, executed):
        self.executed = executed

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


class _OrderPool:
    def __init__(self, executed):
        self.conn = _OrderConn(executed)

    def acquire(self):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def cm():
            yield self.conn
        return cm()


@pytest.fixture
def order_stubs(monkeypatch):
    executed = []
    ordered = []

    async def read_real_cart():
        return {"items": []}, ""

    async def rows_by_ref(slug):
        return {}

    async def persist(slug, cart, by_ref):
        return {"session_id": 7, "items_persisted": 1}

    async def reconcile(slug, cart):
        return {"measured": True, "ok": False, "reason": "écart", "per_food": [], "counts": {}}

    async def noop(*args, **kwargs):
        return None

    async def create_order():
        ordered.append(True)
        return {"orderId": "o1"}

    async def get_pool(dsn):
        return _OrderPool(executed)

    for name, fn in (("_read_real_cart", read_real_cart), ("_cart_rows_by_ref", rows_by_ref),
                     ("_persist_real_cart", persist), ("_reconcile", reconcile),
                     ("get_pool", get_pool)):
        monkeypatch.setattr(app_module, name, fn)
    monkeypatch.setattr(app_module.gate_engine, "record_verify", noop)
    monkeypatch.setattr(app_module.gate_engine, "require_gates", noop)
    monkeypatch.setattr(app_module.drive_a, "create_order", create_order)
    return executed, ordered


def test_commander_reconciliation_ko_sans_motif_refuse(order_stubs):
    executed, ordered = order_stubs
    with pytest.raises(HTTPException) as e:
        asyncio.run(app_module.order_cart(app_module.CartOrder(menu_slug="2026-w41")))
    assert e.value.status_code == 409
    assert "réconciliation" in cast(dict, e.value.detail)["reason"]
    assert ordered == [] and executed == []


def test_commander_reconciliation_ko_avec_motif_passe_et_note(order_stubs):
    executed, ordered = order_stubs
    body = app_module.CartOrder(menu_slug="2026-w41", override_reason="accord Julien")
    asyncio.run(app_module.order_cart(body))
    assert ordered == [True]
    assert len(executed) == 1
    assert executed[0][1] == (7, " — écart assumé : accord Julien")

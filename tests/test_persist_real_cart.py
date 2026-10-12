"""La commande trace le produit, son prix et sa marque lus chez Drive A (#180)."""

import asyncio

from backend import app as app_module


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Conn:
    def __init__(self):
        self.inserts = []

    def transaction(self):
        return _Tx()

    async def fetchval(self, sql, *args):
        return 7

    async def execute(self, sql, *args):
        self.inserts.append(args)


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def _persist(monkeypatch, lines, by_ref):
    conn = _Conn()

    async def fake_pool(_dsn):
        return _Pool(conn)

    monkeypatch.setattr(app_module, "get_pool", fake_pool)
    asyncio.run(app_module._persist_real_cart("menu-x", {"lines": lines}, by_ref))
    return conn.inserts


def test_prix_marque_et_produit_sont_traces(monkeypatch):
    line = {"name": "Lait", "brand": "Drive A", "product_id": "P1", "offer_id": "O1",
            "quantity": 2, "unit_price": 1.1, "total_price": 2.2}
    (args,) = _persist(monkeypatch, [line], {"O1": {"requested": "lait", "drive_a_id": "A1"}})
    assert args[3] == "P1"
    assert args[4:7] == (1.1, 2.2, "Drive A")
    assert args[7] == 2


def test_ligne_sans_row_garde_son_product_id_et_prix_absent_reste_null(monkeypatch):
    (args,) = _persist(monkeypatch, [{"name": "Pain", "product_id": "P9", "quantity": 1}], {})
    assert args[3] == "P9"
    assert args[4:7] == (None, None, None)


def test_repli_sur_le_product_id_de_la_ligne_appariee(monkeypatch):
    line = {"name": "Riz", "offer_id": "O2", "quantity": 1}
    (args,) = _persist(monkeypatch, [line], {"O2": {"product_id": "PR"}})
    assert args[3] == "PR"

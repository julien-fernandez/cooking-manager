"""Une décision sur un nom absent de la file ne réécrit rien avant de dire 404."""

import asyncio

import pytest
from fastapi import HTTPException

from backend import app as app_module


class _Conn:
    async def fetch(self, sql, *args):
        return [{"key": "lait"}]

    async def fetchval(self, sql, *args):
        return None

    async def execute(self, sql, *args):
        return "UPDATE 0"


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


def test_un_nom_hors_file_ne_reecrit_rien(monkeypatch):
    conn, applied = _Conn(), []

    async def fake_pool(_dsn):
        return _Pool(conn)

    async def fake_apply(_conn, ref, decision):
        applied.append((ref, decision))
        return {"recipe_ingredient": 3}

    monkeypatch.setattr(app_module, "get_pool", fake_pool)
    monkeypatch.setattr(app_module, "_apply_food_key", fake_apply)
    body = app_module.ArbitrationBatch(decisions=[
        app_module.ArbitrationDecision(subject="food_key", ref="inconnu", decision="lait")])

    with pytest.raises(HTTPException) as err:
        asyncio.run(app_module.decide_arbitration(body))

    assert err.value.status_code == 404
    assert applied == [], "le 404 doit précéder toute écriture : sinon un rejeu double l'effet"

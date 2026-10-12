"""pantry-confirm désigne une ligne par `id` (revue iPad) ou par nom (agent) — spec 01 § 8.3."""

import asyncio
import datetime
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from backend import app as app_module

ITEMS = [
    {"id": 7, "name": "Miel", "section": "Épicerie sucrée", "food_key": "miel"},
    {"id": 8, "name": "Miel", "section": "Petit-déjeuner", "food_key": "miel"},
]


class Conn:
    def __init__(self):
        self.updated = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetch(self, sql, *args):
        if "WHERE id = $1" in sql:
            return [r for r in ITEMS if r["id"] == args[0]]
        return [r for r in ITEMS if r["name"].lower() == args[0].lower()]

    async def fetchrow(self, sql, *args):
        if sql.lstrip().startswith("UPDATE pantry_item"):
            self.updated.append(args[0])
            return {"id": args[0], "name": "Miel", "status": args[1]}
        return {"menu_slug": args[0], "confirmed_at": datetime.date.today(), "blind": False,
                "reason": None, "lines_count": args[3]}


class Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture
def conn(monkeypatch):
    c = Conn()

    async def get_pool(dsn):
        return Pool(c)

    async def is_staple(conn, key):
        return False

    monkeypatch.setattr(app_module, "get_pool", get_pool)
    monkeypatch.setattr(app_module, "_is_staple_food", is_staple)
    return c


def confirm(*lines):
    body = app_module.PantryConfirmRequest(
        lines=[app_module.PantryConfirmLine(**ln) for ln in lines])
    return asyncio.run(app_module.confirm_pantry("2026-w41", body))


def refused_of(error) -> list[dict]:
    detail = error.value.detail
    assert isinstance(detail, dict)
    return list(detail["refused"])


def test_par_id_contourne_l_homonyme(conn):
    confirm({"id": 8, "name": "Miel", "verdict": "absent"})
    assert conn.updated == [8]


def test_par_nom_homonyme_toujours_refuse(conn):
    with pytest.raises(HTTPException) as e:
        confirm({"name": "Miel", "verdict": "absent"})
    assert e.value.status_code == 422


def test_id_introuvable_refuse_avec_son_id(conn):
    with pytest.raises(HTTPException) as e:
        confirm({"id": 99, "name": "Miel", "verdict": "absent"})
    assert refused_of(e)[0]["id"] == 99
    assert conn.updated == []


def test_corrige_sans_quantite_refuse_rien_ecrit(conn):
    with pytest.raises(HTTPException) as e:
        confirm({"id": 7, "name": "Miel", "verdict": "corrected", "qty_text": "un peu"})
    assert e.value.status_code == 422 and refused_of(e)[0]["id"] == 7
    assert conn.updated == []

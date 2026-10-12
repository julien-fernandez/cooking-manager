"""POST /api/menus ne publie pas : `active` sur un menu non actif passe par PATCH et ses gates."""

import asyncio
from typing import cast
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from backend import app as app_module


class FakeConn:
    def __init__(self, existing):
        self.existing = existing
        self.upserts = 0

    async def fetchval(self, sql, slug):
        return self.existing

    async def fetchrow(self, sql, *args):
        self.upserts += 1
        return {"id": 1, "slug": args[0], "title": args[1], "inserted": False}


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


def post(monkeypatch, existing, status):
    conn = FakeConn(existing)

    async def get_pool(dsn):
        return FakePool(conn)

    async def link(c):
        return 0, 0

    async def skip(c, slug):
        return None

    monkeypatch.setattr(app_module, "get_pool", get_pool)
    monkeypatch.setattr(app_module, "_link_meals", link)
    monkeypatch.setattr(app_module, "_skip_gone_cart_lines", skip)
    menu = app_module.MenuCreate(title="S41", slug="s41", status=status)
    return conn, lambda: asyncio.run(app_module.create_menu(menu))


@pytest.mark.parametrize("existing", [None, "proposed", "archived"])
def test_creer_active_sur_menu_non_actif_refuse(monkeypatch, existing):
    conn, call = post(monkeypatch, existing, "active")
    with pytest.raises(HTTPException) as e:
        call()
    assert e.value.status_code == 409
    detail = cast(dict, e.value.detail)
    assert detail["error"] == "gate" and detail["transition"] == "publish"
    assert conn.upserts == 0


def test_reecrire_un_menu_deja_actif_passe(monkeypatch):
    conn, call = post(monkeypatch, "active", "active")
    assert call()["slug"] == "s41"
    assert conn.upserts == 1


def test_creer_proposed_passe(monkeypatch):
    conn, call = post(monkeypatch, None, "proposed")
    call()
    assert conn.upserts == 1

"""PATCH /api/menus/{slug} : le seul statut change, et un seul menu reste `active` (skills #71)."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from backend import app as app_module


class FakeConn:
    def __init__(self, menus: dict[str, str]):
        self.menus = menus

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, sql, slug, status):
        if slug not in self.menus:
            return None
        self.menus[slug] = status
        return {"slug": slug}

    async def fetch(self, sql, slug):
        others = [s for s, st in self.menus.items() if st == "active" and s != slug]
        for s in others:
            self.menus[s] = "archived"
        return [{"slug": s} for s in others]


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture
def menus(monkeypatch):
    state = {"2026-09-07": "active", "2026-09-21": "active", "2026-10-05": "proposed"}

    async def get_pool(dsn):
        return FakePool(FakeConn(state))

    monkeypatch.setattr(app_module, "get_pool", get_pool)
    async def require_gates(slug, transition, override_reason="", actor="agent"):
        return None

    monkeypatch.setattr(app_module.gate_engine, "require_gates", require_gates)
    return state


def patch(slug, status):
    body = app_module.MenuStatusUpdate(status=status)
    return asyncio.run(app_module.update_menu_status(slug, body))


def test_la_route_est_declaree():
    routes = {(getattr(r, "path", ""), m) for r in app_module.app.routes
              for m in getattr(r, "methods", ())}
    assert ("/api/menus/{slug}", "PATCH") in routes


def test_activer_la_semaine_archive_les_anciennes(menus):
    result = patch("2026-10-05", "active")
    assert result == {"slug": "2026-10-05", "status": "active",
                      "archived": ["2026-09-07", "2026-09-21"]}
    assert menus == {"2026-09-07": "archived", "2026-09-21": "archived",
                     "2026-10-05": "active"}


def test_archiver_ne_touche_pas_aux_autres(menus):
    assert patch("2026-09-07", "archived")["archived"] == []
    assert menus["2026-09-21"] == "active"


def test_statut_inconnu_refuse(menus):
    with pytest.raises(HTTPException) as e:
        patch("2026-10-05", "served")
    assert e.value.status_code == 422
    assert menus["2026-10-05"] == "proposed"


def test_menu_inconnu_404(menus):
    with pytest.raises(HTTPException) as e:
        patch("2026-10-12", "active")
    assert e.value.status_code == 404
    assert menus["2026-09-07"] == "active"


def test_le_post_refuse_aussi_un_statut_inconnu(menus):
    with pytest.raises(HTTPException) as e:
        asyncio.run(app_module.create_menu(app_module.MenuCreate(title="x", status="draft")))
    assert e.value.status_code == 422


def test_seul_le_statut_se_patche():
    with pytest.raises(ValueError):
        app_module.MenuStatusUpdate.model_validate({"status": "active", "meals": []})

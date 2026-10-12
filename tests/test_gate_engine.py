"""Le moteur côté I/O : charger, évaluer, journaliser, refuser — sans base (FakePool)."""

import asyncio
import datetime
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from backend import app as app_module
from backend import db
from backend import gates as engine
from cooking_manager import gates as g


def test_table_dans_le_schema_et_la_migration_index_en_migration_seulement():
    assert "CREATE TABLE IF NOT EXISTS gate_verdict" in db.SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS gate_verdict" in db.MIGRATIONS_SQL
    assert "idx_gate_verdict_menu" not in db.SCHEMA_SQL
    assert "idx_gate_verdict_menu" in db.MIGRATIONS_SQL


def test_relecture_d_une_ligne_de_base_reste_serialisable():
    row = {"state": g.KO, "value": Decimal("1"), "detail": '{"missing": ["persil-plat"]}',
           "cart_fingerprint": "abc",
           "measured_at": datetime.datetime(2026, 10, 7, 10, 0, tzinfo=datetime.UTC)}
    decoded = engine.decode_verdict_row(row)
    assert decoded["value"] == 1.0 and decoded["detail"] == {"missing": ["persil-plat"]}
    json.dumps(decoded)


def ok_inputs():
    return {
        "tablee_unresolved": {"days": ["2026-10-06"], "unsynced": []},
        "slots_uncomposed": {"slots_uncomposed": {"measured": True, "reason": "", "slots": []},
                             "meals_unmatched": []},
        "meals_orphan": {"slots_uncomposed": {"measured": True, "reason": "", "slots": []},
                         "meals_unmatched": []},
        "conflicts_uncovered": {"leftovers_unsourced": [], "conflicts_uncovered": 0,
                                "parts_unmentioned": []},
        "parts_unmentioned": {"leftovers_unsourced": [], "conflicts_uncovered": 0,
                              "parts_unmentioned": []},
        "pantry_blind": {"ok": False, "blind": False, "reason": "non confirmé", "note": None},
        "food_pending": [],
        "cart_asked": {"lines": []},
        "cart_stale": {"lines": []},
        "verify_missing": {"last": None, "fingerprint": "x"},
        "published": {"status": "proposed", "active_menus": 0},
    }


def test_evaluate_rend_le_rapport_et_les_resultats(monkeypatch):
    async def load_inputs(slug):
        return ok_inputs(), {}
    monkeypatch.setattr(engine, "load_inputs", load_inputs)
    report, results = asyncio.run(engine.evaluate("2026-w41"))
    assert results["pantry_blind"].state == g.KO
    assert report["transitions"]["elect"] == {"allowed": False, "blocking": ["pantry_blind"]}
    json.dumps(report)


def test_un_loader_qui_leve_rend_non_mesure():
    async def boom():
        raise HTTPException(500, "compat cassée")
    loaded = asyncio.run(engine._safe(boom()))
    assert isinstance(loaded, g.LoadError) and "compat cassée" in loaded.message


class MenuConn:
    def __init__(self, menu):
        self.menu = menu

    async def fetchrow(self, sql, *args):
        if "FROM menu WHERE slug" in sql:
            return self.menu
        return None

    async def fetch(self, sql, *args):
        return []

    async def fetchval(self, sql, *args):
        return 0


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


def test_menu_inconnu_404(monkeypatch):
    async def get_pool(dsn):
        return FakePool(MenuConn(None))
    monkeypatch.setattr(app_module, "get_pool", get_pool)
    with pytest.raises(HTTPException) as e:
        asyncio.run(engine.load_inputs("2026-w99"))
    assert e.value.status_code == 404


def test_route_gates_declaree():
    routes = {(getattr(r, "path", ""), m) for r in app_module.app.routes
              for m in getattr(r, "methods", ())}
    assert ("/api/menus/{slug}/gates", "GET") in routes


@pytest.fixture
def judged(monkeypatch):
    """`evaluate` figé sur un garde-manger non revu ; le journal capturé."""
    written = []

    async def evaluate(slug):
        inputs = ok_inputs()
        results = {gate.id: g.run(gate, inputs.get(gate.id)) for gate in g.GATES}
        return g.report(slug, results, {}, "t"), results

    async def journal(slug, transition, results, outcome, override_reason, actor,
                      fingerprint=None):
        written.append({"transition": transition, "ids": [r.id for r in results],
                        "outcome": outcome, "reason": override_reason, "actor": actor})

    monkeypatch.setattr(engine, "evaluate", evaluate)
    monkeypatch.setattr(engine, "journal", journal)
    return written


def test_refus_409_et_journal_refuse(judged):
    with pytest.raises(HTTPException) as e:
        asyncio.run(engine.require_gates("2026-w41", "elect"))
    assert e.value.status_code == 409
    detail: Any = e.value.detail
    assert detail["error"] == "gate" and detail["transition"] == "elect"
    assert [r["id"] for r in detail["red"]] == ["pantry_blind"]
    assert "window_undecided" in detail["not_wired"]
    assert judged[-1]["outcome"] == "refusé"
    assert judged[-1]["ids"] == [gate.id for gate in g.required_gates("elect") if gate.wired]


def test_forcage_passe_et_se_journalise(judged):
    asyncio.run(engine.require_gates("2026-w41", "elect", "Julien a revu à l'œil", "agent"))
    assert judged[-1] == {"transition": "elect", "ids": judged[-1]["ids"], "outcome": "forcé",
                          "reason": "Julien a revu à l'œil", "actor": "agent"}


def test_motif_fait_d_espaces_ne_force_rien(judged):
    with pytest.raises(HTTPException) as e:
        asyncio.run(engine.require_gates("2026-w41", "elect", "   "))
    assert e.value.status_code == 409


def test_transition_verte_passe(judged):
    asyncio.run(engine.require_gates("2026-w41", "publish"))
    assert judged[-1]["outcome"] == "passé"


def test_acteur_inconnu_422(judged):
    with pytest.raises(HTTPException) as e:
        asyncio.run(engine.require_gates("2026-w41", "publish", actor="robot"))
    assert e.value.status_code == 422


class JournalConn:
    def __init__(self):
        self.rows = []

    async def executemany(self, sql, rows):
        assert sql.lstrip().startswith("INSERT INTO gate_verdict")
        self.rows.extend(rows)

    async def fetch(self, sql, *args):
        return [{"id": 1, "status": "pushed", "quantity": 2}]


def test_record_verify_journalise_avec_l_empreinte(monkeypatch):
    conn = JournalConn()

    async def get_pool(dsn):
        return FakePool(conn)
    monkeypatch.setattr(app_module, "get_pool", get_pool)
    payload = {"measured": True, "per_food": [{"food": "persil-plat", "verdict": "MANQUE"}]}
    result = asyncio.run(engine.record_verify("2026-w41", payload))
    assert result.state == g.KO
    (row,) = conn.rows
    assert row[1:4] == ("verify_missing", "verify", g.KO)
    assert row[7] == "mesuré"
    assert row[10] == g.cart_fingerprint([{"id": 1, "status": "pushed", "quantity": 2}])


def test_record_verify_refuse_un_acteur_inconnu():
    with pytest.raises(HTTPException) as e:
        asyncio.run(engine.record_verify("2026-w41", {"measured": False}, "robot"))
    assert e.value.status_code == 422

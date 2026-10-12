"""La fenêtre « à partir d'aujourd'hui » des gates 1 à 4 (ADR 0044) — sans base."""

import asyncio
import datetime
import json
from contextlib import asynccontextmanager

import pytest

from backend import app as app_module
from backend import gates as engine
from cooking_manager import gates as g
from cooking_manager import presence

PAST = datetime.date(2026, 10, 5)
FUTURE = datetime.date(2026, 10, 9)
TODAY = datetime.date(2026, 10, 7)


def meal(meal_id, day, dish, **extra):
    return {"meal_id": meal_id, "day_label": "jour", "day": day, "slot": "lunch",
            "dish": dish, "position": meal_id, "match_kind": "recipe", "leftovers_of": None,
            "ingredients": [], **extra}


def part_line(meal_id):
    return {"meal_id": meal_id, "recipe_id": meal_id, "recipe_slug": f"r{meal_id}",
            "name": "tofu", "name_normalized": "tofu", "raw": "tofu", "position": 1,
            "for_person_id": 7, "replaces_position": None}


class CompatConn:
    def __init__(self, meals, details, steps):
        self.meals, self.details, self.steps = meals, details, steps

    async def fetchrow(self, sql, *args):
        return {"slug": "s", "title": "S"}

    async def fetch(self, sql, *args):
        if "GROUP BY mm.id" in sql:
            return self.meals
        if "recipe_ingredient ri ON ri.recipe_id = mm.recipe_id\n                WHERE" in sql:
            return self.details
        if "recipe_step rs" in sql:
            return self.steps
        return []


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture
def compat(monkeypatch):
    def run(meals, details, steps, **kwargs):
        async def get_pool(dsn):
            return FakePool(CompatConn(meals, details, steps))

        async def nothing(conn):
            return {}

        monkeypatch.setattr(app_module, "get_pool", get_pool)
        monkeypatch.setattr(app_module, "load_household_config", nothing)
        monkeypatch.setattr(app_module, "load_referential_from_db", nothing)
        monkeypatch.setattr(app_module, "load_convives_from_db", nothing)
        monkeypatch.setattr(app_module, "_memberships", nothing)
        monkeypatch.setattr(app_module, "_person_ids", nothing)
        monkeypatch.setattr(presence, "attendees", lambda *a, **k: [])
        return asyncio.run(app_module.menu_compatibility("s", **kwargs))
    return run


def test_sans_from_date_la_compat_juge_tout(compat):
    meals = [meal(1, PAST, "Passé"), meal(2, FUTURE, "À venir"), meal(3, None, "Sans date")]
    out = compat(meals, [], [])
    assert out["meals_checked"] == 3


def test_from_date_exclut_les_repas_passes_et_garde_ceux_sans_date(compat):
    meals = [meal(1, PAST, "Passé"), meal(2, FUTURE, "À venir"), meal(3, None, "Sans date")]
    out = compat(meals, [], [], from_date=TODAY.isoformat())
    assert [r["dish"] for r in out["results"]] == ["À venir", "Sans date"]


def test_part_non_nommee_passee_ne_compte_pas_mais_a_venir_compte(compat):
    meals = [meal(1, PAST, "Passé"), meal(2, FUTURE, "À venir")]
    details = [part_line(1), part_line(2)]
    steps = [{"meal_id": 1, "text": "Cuire le riz"}, {"meal_id": 2, "text": "Cuire le riz"}]
    sans = compat(meals, details, steps)
    avec = compat(meals, details, steps, from_date=TODAY.isoformat())
    assert [p["recipe_slug"] for p in sans["parts_unmentioned"]] == ["r1", "r2"]
    assert [p["recipe_slug"] for p in avec["parts_unmentioned"]] == ["r2"]


def test_reste_dans_la_fenetre_dont_la_source_est_passee_reste_source(compat):
    source = meal(1, PAST, "Gratin")
    reste = meal(2, FUTURE, "Reste de gratin", match_kind="leftovers", leftovers_of=1)
    details = [{**part_line(1), "for_person_id": None}]
    out = compat([source, reste], details, [], from_date=TODAY.isoformat())
    assert out["leftovers_unsourced"] == []
    assert out["meals_checked"] == 1


def test_reste_sans_source_passe_ne_compte_pas_a_venir_compte(compat):
    passe = meal(1, PAST, "Reste", match_kind="leftovers")
    avenir = meal(2, FUTURE, "Reste", match_kind="leftovers")
    out = compat([passe, avenir], [], [], from_date=TODAY.isoformat())
    assert len(out["leftovers_unsourced"]) == 1


def test_rapport_porte_la_fenetre():
    results = {gate.id: g.run(gate, None) for gate in g.GATES}
    window = {"from_date": "2026-10-07", "reason": "r"}
    assert g.report("s", results, {}, "t", window=window)["window"] == window
    assert "window" not in g.report("s", results, {}, "t")


def test_tablee_sans_jour_a_venir_motif():
    result = g.run(g.GATES_BY_ID["tablee_unresolved"], {"days": [], "unsynced": []})
    assert result.state == g.UNMEASURED
    assert "à venir" in result.detail["reason"]


class DaysConn:
    async def fetchrow(self, sql, *args):
        return None if "gate_verdict" in sql else {"id": 1, "status": "proposed"}

    async def fetch(self, sql, *args):
        if "DISTINCT day" in sql:
            return [{"day": PAST}, {"day": FUTURE}]
        if "child_week_presence" in sql:
            return [{"week_monday": FUTURE - datetime.timedelta(days=FUTURE.weekday())}]
        return []

    async def fetchval(self, sql, *args):
        return 0


def test_load_inputs_passe_la_date_du_jour_et_ne_garde_que_les_jours_a_venir(monkeypatch):
    seen = {}

    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return TODAY

    async def get_pool(dsn):
        return FakePool(DaysConn())

    async def shopping(slug, covers=None, from_date=None):
        seen["shopping"] = from_date
        return {"lines": []}

    async def compat_(slug, from_date=None):
        seen["compat"] = from_date
        return {}

    async def other(slug):
        return {}

    monkeypatch.setattr(engine.datetime, "date", FrozenDate)
    monkeypatch.setattr(app_module, "get_pool", get_pool)
    monkeypatch.setattr(app_module, "menu_shopping_list", shopping)
    monkeypatch.setattr(app_module, "menu_compatibility", compat_)
    monkeypatch.setattr(app_module, "_confirmation_state", other)
    monkeypatch.setattr(app_module, "read_cart", other)
    inputs, _ = asyncio.run(engine.load_inputs("s"))
    assert seen == {"shopping": "2026-10-07", "compat": "2026-10-07"}
    assert inputs["tablee_unresolved"] == {"days": [FUTURE.isoformat()], "unsynced": []}


def test_evaluate_ajoute_la_fenetre_au_rapport(monkeypatch):
    async def load_inputs(slug):
        return {}, {}
    monkeypatch.setattr(engine, "load_inputs", load_inputs)
    report, _ = asyncio.run(engine.evaluate("s"))
    assert report["window"]["from_date"] == datetime.date.today().isoformat()
    json.dumps(report)

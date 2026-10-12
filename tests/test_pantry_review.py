"""La revue ciblée : les lignes du garde-manger dont la semaine dépend, une fois chacune (spec 01 § 8.2)."""

import asyncio
import datetime
from contextlib import asynccontextmanager

from backend import app as app_module
from cooking_manager.pantry_review import review_lines


def line(name, outcome, item=None, recipes=("Poulet au miel",)):
    return {"name": name, "qty": 2, "unit": "c.s.", "recipes": list(recipes),
            "outcome": outcome, "pantry": item}


MIEL = {"id": 7, "name": "Miel", "qty_text": "3 pots 250 g", "status": "ok"}
CUMIN = {"id": 9, "name": "Cumin", "qty_text": "", "status": "ok"}
RIZ = {"id": 4, "name": "Riz", "qty_text": "1 sachet", "status": "ok"}


def test_garde_ce_dont_la_semaine_depend():
    lines = [line("miel", "suffisant", MIEL), line("cumin", "placard", CUMIN),
             line("tomate", "absent"), line("riz", "inconnu", RIZ)]
    assert [r["id"] for r in review_lines(lines)] == [7, 4]


def test_deux_besoins_sur_le_meme_article_une_seule_ligne():
    lines = [line("miel", "suffisant", MIEL),
             line("miel", "insuffisant", MIEL, recipes=("Yaourt miel noix",))]
    (only,) = review_lines(lines)
    assert [n["recipes"] for n in only["needs"]] == [["Poulet au miel"], ["Yaourt miel noix"]]


def test_inconnu_ouvre_la_quantite():
    (riz,) = review_lines([line("riz", "inconnu", RIZ)])
    assert riz["ask_qty"] is True


def test_route_trie_par_rayon(monkeypatch):
    seen = {}

    async def shopping(slug, from_date=None):
        seen["from_date"] = from_date
        return {"lines": [line("miel", "suffisant", MIEL), line("riz", "inconnu", RIZ)],
                "pantry": {"confirmation": {"ok": False, "blind": False}}}

    class Conn:
        async def fetch(self, sql, ids):
            return [{"id": 7, "section": "Épicerie sucrée"}, {"id": 4, "section": "Céréales"}]

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Conn()

    async def get_pool(dsn):
        return Pool()

    monkeypatch.setattr(app_module, "menu_shopping_list", shopping)
    monkeypatch.setattr(app_module, "get_pool", get_pool)
    out = asyncio.run(app_module.menu_pantry_review("2026-w41"))
    assert [r["name"] for r in out["lines"]] == ["Riz", "Miel"]
    assert seen["from_date"] == datetime.date.today().isoformat()
    assert out["count"] == 2 and out["confirmation"] == {"ok": False, "blind": False}

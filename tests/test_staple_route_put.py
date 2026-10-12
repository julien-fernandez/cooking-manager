"""Un basique se déclare par aliment : ses lignes vivantes, une ligne finie ravivée, ou une ligne créée dans « Fond de cuisine »."""

import asyncio
import inspect
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from backend import app as app_module

TRASH = "À jeter / périmés"


class FakeConn:
    """Rejoue les quatre écritures de la route sur des lignes en mémoire, d'après leur texte SQL."""

    def __init__(self, foods, lines):
        self.foods, self.lines, self.next_id, self.now = foods, lines, 100, 9

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, sql, key):
        return self.foods.get(key)

    async def execute(self, sql, food_key, target):
        if "WHERE id = $2" in sql:
            hit = [ln for ln in self.lines if ln["id"] == target and ln["food_key"] is None]
        else:
            hit = [ln for ln in self.lines if ln["food_key"] is None and ln["name_normalized"] in target]
        for ln in hit:
            ln["food_key"] = food_key

    async def fetch(self, sql, food_key, second):
        if "section <> $2" in sql:
            dead = [ln for ln in self.lines if ln["food_key"] == food_key and ln["status"] == "out"
                    and ln.get("xstatus", "out") == "out" and ln["section"] != second]
            last = max((ln.get("updated_at", 0) for ln in dead), default=None)
            hit = [ln for ln in dead if ln.get("updated_at", 0) == last]
            for ln in hit:
                ln.update(status="ok")
            return [{"id": ln["id"]} for ln in hit]
        out = "SET status = 'out'" in sql
        hit = [ln for ln in self.lines if ln["food_key"] == food_key and ln["status"] in second]
        for ln in hit:
            ln.update(status="out" if out else "ok", updated_at=self.now)
        return [{"id": ln["id"]} for ln in hit]

    async def fetchval(self, sql, *args):
        name, name_normalized, section, status, food_key = args
        same = [ln for ln in self.lines if ln["name_normalized"] == name_normalized and ln["section"] == section]
        if same:
            if same[0]["food_key"] not in (None, food_key):
                return None
            same[0].update(status=status, food_key=food_key)
            return same[0]["id"]
        self.next_id += 1
        self.lines.append({"id": self.next_id, "name_normalized": name_normalized, "section": section,
                           "status": status, "food_key": food_key})
        return self.next_id


@pytest.fixture
def db(monkeypatch):
    def make(foods, lines):
        conn = FakeConn(foods, lines)

        class Pool:
            @asynccontextmanager
            async def acquire(self):
                yield conn

        async def get_pool(dsn):
            return Pool()
        monkeypatch.setattr(app_module, "get_pool", get_pool)
        return conn
    return make


CUMIN = {"key": "cumin", "name": "Cumin", "pantry_staple": True}
OIL = {"key": "huile olive", "name": "Huile d'olive", "pantry_staple": True}


def line(id_, *, food_key: str | None = "cumin", status="ok", name="cumin", section="Épices & Herbes", **kw):
    return {"id": id_, "food_key": food_key, "status": status, "name_normalized": name,
            "section": section, "qty_value": None, "unit": None, **kw}


def put(key, status, item_id=None):
    return asyncio.run(app_module.set_staple(key, app_module.StapleState(status=status, item_id=item_id)))


def test_je_n_en_ai_plus_passe_les_lignes_vivantes_out_et_garde_leur_quantite(db):
    """Le statut suffit à dire « fini » : effacer la quantité rendait le geste irréversible (#201)."""
    conn = db({"huile olive": OIL}, [
        line(1, food_key="huile olive", name="huile d olive", qty_value=1000.0, unit="ml"),
        line(2, food_key="huile olive", name="huile d olive", status="out", xstatus="périmé", section=TRASH)])
    assert put("huile olive", "out")["updated"] == [1]
    assert (conn.lines[0]["status"], conn.lines[0]["qty_value"], conn.lines[0]["unit"]) == ("out", 1000.0, "ml")
    assert conn.lines[1]["xstatus"] == "périmé"


def test_je_l_ai_finalement_ravive_la_derniere_ligne_finie_hors_a_jeter(db):
    conn = db({"cumin": CUMIN}, [line(1, status="out", updated_at=2), line(3, status="out", updated_at=1),
                                 line(2, status="out", xstatus="à-jeter", section=TRASH, updated_at=5)])
    result = put("cumin", "ok")
    assert (result["updated"], result["created"]) == ([1], None)
    assert [ln["status"] for ln in conn.lines] == ["ok", "out", "out"]


def test_aller_retour_out_ok_rend_la_quantite_de_toutes_les_lignes(db):
    """« Je n'en ai plus » touché par erreur sur `sucre` (4 lignes) s'annule à l'identique (#201)."""
    conn = db({"cumin": CUMIN}, [line(1, qty_text="1 pot", qty_value=1.0, unit="pot"),
                                 line(2, qty_text="50 g", qty_value=50.0, unit="g"),
                                 line(4, status="out", updated_at=1)])
    put("cumin", "out")
    assert sorted(put("cumin", "ok")["updated"]) == [1, 2]
    assert [(ln["status"], ln.get("qty_text"), ln["qty_value"], ln["unit"]) for ln in conn.lines] == [
        ("ok", "1 pot", 1.0, "pot"), ("ok", "50 g", 50.0, "g"), ("out", None, None, None)]


def test_je_l_ai_cree_la_ligne_dans_fond_de_cuisine(db):
    conn = db({"cumin": CUMIN}, [])
    result = put("cumin", "ok")
    assert result["created"] == 101
    assert conn.lines[0]["section"] == "Fond de cuisine" and conn.lines[0]["food_key"] == "cumin"


def test_je_n_en_ai_pas_cree_une_ligne_finie(db):
    conn = db({"cumin": CUMIN}, [])
    assert put("cumin", "out")["created"] == 101
    assert conn.lines[0]["status"] == "out"


def test_la_ligne_vue_par_son_nom_est_rattachee_au_lieu_d_un_homonyme(db):
    """Le verdict s'appuyait sur « Cumin moulu Ducros » sans aliment : le geste la rattache, il n'en crée pas d'autre."""
    conn = db({"cumin": CUMIN}, [line(5, food_key=None, name="cumin moulu ducro")])
    result = put("cumin", "out", item_id=5)
    assert (result["updated"], result["created"]) == ([5], None)
    assert (conn.lines[0]["food_key"], conn.lines[0]["status"]) == ("cumin", "out")
    assert len(conn.lines) == 1


def test_une_ligne_au_nom_de_l_aliment_sans_aliment_est_rattachee(db):
    conn = db({"cumin": CUMIN}, [line(7, food_key=None, status="out", section="Fond de cuisine")])
    assert put("cumin", "ok")["updated"] == [7]
    assert (conn.lines[0]["status"], conn.lines[0]["food_key"]) == ("ok", "cumin")


def test_une_ligne_homonyme_d_un_autre_aliment_n_est_pas_reprise(db):
    db({"cumin": CUMIN}, [line(8, food_key="carvi", section="Fond de cuisine")])
    with pytest.raises(HTTPException) as e:
        put("cumin", "ok")
    assert e.value.status_code == 409


def test_aliment_inconnu_404(db):
    db({}, [])
    with pytest.raises(HTTPException) as e:
        put("cumin", "ok")
    assert e.value.status_code == 404


def test_aliment_ordinaire_422(db):
    db({"riz": {"key": "riz", "name": "Riz", "pantry_staple": False}}, [])
    with pytest.raises(HTTPException) as e:
        put("riz", "ok")
    assert e.value.status_code == 422


def test_statut_hors_ok_out_422(db):
    db({"cumin": CUMIN}, [])
    with pytest.raises(HTTPException) as e:
        put("cumin", "low")
    assert e.value.status_code == 422


def test_le_sql_vise_les_lignes_vivantes_et_epargne_les_perimes():
    source = inspect.getsource(inspect.unwrap(app_module.set_staple))
    assert "status = ANY($2::text[])" in source
    assert "qty_value = NULL" not in source
    assert "xstatus = 'out'" in source and "section <> $2" in source
    assert "WHERE pantry_item.food_key IS NULL OR pantry_item.food_key = EXCLUDED.food_key" in source


def test_la_liste_donne_l_id_de_la_ligne_vue():
    assert '"id": verdict.pantry_item.item_id' in inspect.getsource(
        inspect.unwrap(app_module.menu_shopping_list))

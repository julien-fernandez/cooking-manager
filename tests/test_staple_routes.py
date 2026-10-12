"""Les compteurs du placard se lisent avant les lignes, comme les autres compteurs de doute (ADR 0043)."""

import inspect

from backend import app as app_module
from cooking_manager.verification import covered_by_stock_for, lines_to_buy, lines_stock_unknown


def _source(route) -> str:
    return inspect.getsource(inspect.unwrap(route))


def test_la_liste_dit_le_placard_avant_les_lignes():
    source = _source(app_module.menu_shopping_list)
    for key in ('"staples_undeclared"', '"staples_unlinked"'):
        assert source.index(key) < source.index('"lines": lines'), key


def test_la_carte_dit_le_placard_avant_les_recettes():
    source = _source(app_module.menu_ingredient_map)
    for key in ('"staples_undeclared"', '"staples_unlinked"'):
        assert source.index(key) < source.index('"recipes"'), key


def test_le_garde_manger_charge_les_basiques():
    assert "WHERE pantry_staple" in _source(app_module._pantry_from_db)


def test_le_panier_tient_un_basique_present_pour_couvert():
    """POST /api/cart/items origin=menu : un basique au placard n'est pas élu au drive."""
    lines = [{"name": "cumin", "name_normalized": "cumin", "outcome": "placard",
              "assumed_empty": False, "merged_from": []}]
    assert covered_by_stock_for(lines, food_key=None, requested="cumin", keys={})


def test_la_liste_ne_marque_basique_que_sous_le_seuil():
    assert "staple_rule_applies(need, pantry)" in _source(app_module.menu_shopping_list)


def test_verify_ne_reclame_jamais_un_basique_couvert():
    line = {"outcome": "placard", "purchase": None, "assumed_empty": False}
    assert lines_to_buy([line]) == [] and lines_stock_unknown([line]) == []


def test_la_fiche_dit_quels_ingredients_sont_du_placard():
    source = _source(app_module.get_recipe)
    assert "COALESCE(f.pantry_staple, FALSE) AS pantry_staple" in source
    assert "LEFT JOIN food f ON f.key = ri.food_key" in source

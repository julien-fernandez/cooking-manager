"""La route ingredient-map : déclarée, et le doute y précède le rassurant."""

import inspect

from backend import app as app_module


def _source() -> str:
    return inspect.getsource(inspect.unwrap(app_module.menu_ingredient_map))


def test_la_route_est_declaree():
    declared = {getattr(r, "path", "") for r in app_module.app.routes}
    assert "/api/menus/{slug}/ingredient-map" in declared


def test_to_review_et_pantry_precedent_recipes():
    source = _source()
    assert source.index('"to_review"') < source.index('"recipes"')
    assert source.index('"pantry"') < source.index('"recipes"')


def test_un_panier_illisible_se_dit_en_tete():
    assert '"cart_unreadable"' in _source()


def test_la_route_n_ecrit_rien():
    source = _source().upper()
    for verb in ("INSERT ", "UPDATE ", "DELETE "):
        assert verb not in source


def test_la_route_suit_le_meme_calcul_que_verify():
    """Sans `covers` : verify juge la liste par défaut, la page ne doit pas en montrer une autre."""
    assert "covers" not in inspect.signature(app_module.menu_ingredient_map).parameters


def test_les_repas_sans_fiche_se_disent_avant_les_recettes():
    source = _source()
    for key in ('"meals_unmatched"', '"meals_leftovers"', '"slots_uncomposed"'):
        assert source.index(key) < source.index('"recipes"'), key

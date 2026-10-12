"""ADR 0043 : un basique peut être `ok` sans quantité ; un aliment ordinaire, toujours pas (ADR 0036)."""

import inspect

from backend import app as app_module
from cooking_manager.pantry import entry_quantity


def test_basique_ok_sans_quantite_accepte():
    assert entry_quantity("", "ok", staple=True) == (None, None, None)


def test_basique_avec_quantite_la_garde():
    assert entry_quantity("1 pot 120 g", "ok", staple=True) == (120.0, "g", None)


def test_aliment_ordinaire_toujours_refuse():
    value, unit, refusal = entry_quantity("", "ok")
    assert (value, unit) == (None, None) and refusal


def test_les_trois_ecritures_par_ligne_consultent_l_aliment():
    for route in (app_module.update_pantry, app_module.update_pantry_item, app_module.confirm_pantry):
        source = inspect.getsource(inspect.unwrap(route))
        assert "_is_staple_food(conn" in source, route.__name__
        assert "staple=" in source, route.__name__

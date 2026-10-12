"""Une quantité se dit en français : virgule, fractions usuelles, unité au pluriel, arrondi avoué (#204)."""

import pytest

from cooking_manager.quantity_display import format_quantity


@pytest.mark.parametrize("qty,unit,mult,expected", [
    (0.75, "kg", 1, "0,75 kg"),
    (1.5, "c.c.", 1, "1 ½ c.c."),
    (1, "c.c.", 0.75, "¾ c.c."),
    (0.5, "pièce", 1, "½ pièce"),
    (3, "gousse", 0.75, "≈ 2 ½ gousses"),
    (3, "gousse", 1.25, "≈ 4 gousses"),
    (8, "pièce", 1, "8 pièces"),
    (1, "pièce", 0.75, "≈ 1 pièce"),
    (1, "pièce", 1.25, "≈ 1 pièce"),
    (2, "bocal", 1, "2 bocaux"),
    (250, "g", 1, "250 g"),
    (200, "g", 1.25, "250 g"),
    (0.33, None, 1, "⅓"),
    (0.5, "bouquet", 1, "½ bouquet"),
    (1.5, "gousse", 1, "1 ½ gousse"),
    (2, "cuillère à soupe", 1, "2 cuillères à soupe"),
])
def test_quantite_en_francais(qty, unit, mult, expected):
    assert format_quantity(qty, None, unit, mult) == expected


def test_fourchette_au_pluriel_par_sa_borne_haute():
    assert format_quantity(1, 2, "gousse") == "1–2 gousses"


def test_sans_quantite_rien():
    assert format_quantity(None, None, "g") == ""

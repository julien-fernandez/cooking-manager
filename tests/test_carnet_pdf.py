"""Carnet PDF : arrondi des unités comptables et mise à l'échelle des parts."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "carnet_pdf", Path(__file__).resolve().parent.parent / "scripts" / "carnet_pdf.py")
assert _SPEC and _SPEC.loader
carnet = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(carnet)


def ing(qty, unit, **kw):
    base = {"qty_min": qty, "qty_max": None, "unit": unit, "name": "x", "raw": "x",
            "parsed": True, "is_optional": False, "for_person_id": None,
            "for_person": None, "replaces_position": None, "position": 1}
    return {**base, **kw}


def test_piece_mise_a_l_echelle_arrondie_a_l_entier():
    assert carnet.qty_text(ing(3, "pièce"), 5 / 4) == "≈ 4 pièces"


def test_demi_arrondi_vers_le_haut():
    assert carnet.qty_text(ing(2, "pièce"), 5 / 4) == "≈ 3 pièces"


def test_minimum_un():
    assert carnet.qty_text(ing(1, "pièce"), 0.1) == "≈ 1 pièce"


def test_piece_non_mise_a_l_echelle_reste_telle_quelle():
    assert carnet.qty_text(ing(0.5, "pièce"), 1) == "½ pièce"


def test_gramme_garde_l_arrondi_decimal():
    assert carnet.qty_text(ing(200, "g"), 5 / 4) == "250 g"


def test_dose_non_comptable_garde_le_decimal():
    assert carnet.qty_text(ing(1, "gousse"), 1.5) == "1 ½ gousse"


def test_fourchette_arrondie_des_deux_cotes():
    assert carnet.qty_text(ing(2, "pièce", qty_max=3), 5 / 4) == "≈ 3–4 pièces"


def recipe(*ingredients):
    return {"servings": 4, "ingredients": list(ingredients)}


def _riz_et_part():
    return recipe(ing(200, "g", name="riz", position=1),
                  ing(100, "g", name="riz sans gluten", position=2,
                      for_person_id=7, for_person="Lou", replaces_position=1))


def test_une_part_reste_a_une_portion():
    lines = carnet.ingredient_lines(_riz_et_part(), 5)
    assert lines[1][0] == "100 g"
    assert "portion de Lou" in lines[1][1]


def test_ingredient_remplace_compte_portions_moins_parts_sur_base():
    assert carnet.ingredient_lines(_riz_et_part(), 5)[0][0] == "200 g"
    assert carnet.ingredient_lines(_riz_et_part(), 6)[0][0] == "250 g"


def test_les_basiques_sortent_de_la_liste():
    r = recipe(ing(200, "g", name="lentille", position=1),
               ing(1, "c.c.", name="cumin", position=2, pantry_staple=True),
               ing(None, None, name="sel", position=3, pantry_staple=True))
    ordinary, basics = carnet.split_staples(r, 4)
    assert [name for _, name in ordinary] == ["lentille"]
    assert carnet.staples_line(basics) == (
        "<p class='placard'><b>Du placard :</b> 1 c.c. cumin · sel</p>")


def test_sans_basique_aucune_ligne():
    assert carnet.staples_line([]) == ""

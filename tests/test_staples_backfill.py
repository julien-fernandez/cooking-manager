"""Le rattrapage du placard : grouper les lignes par aliment visé, retrouver les ingrédients qui les nomment."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "staples_backfill", Path(__file__).resolve().parent.parent / "scripts" / "staples_backfill.py")
assert _SPEC and _SPEC.loader
backfill = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backfill)


def row(name, food_key=None, section="Épices & Herbes"):
    return {"name": name, "name_normalized": name.lower(), "food_key": food_key, "section": section}


def test_une_ligne_rattachee_garde_son_aliment():
    [group] = backfill.group_candidates([row("Cumin moulu", food_key="cumin")])
    assert (group["food_key"], group["exists"], group["accept"]) == ("cumin", True, False)


def test_deux_lignes_du_meme_nom_font_un_seul_aliment():
    groups = backfill.group_candidates([row("Paprika"), row("paprika", section="Condiments & Huiles")])
    assert len(groups) == 1
    assert groups[0]["pantry_names"] == ["Paprika", "paprika"]


def test_hors_rayons_du_placard_ignore():
    assert backfill.group_candidates([row("Riz", section="Sec — Féculents & Légumineuses")]) == []


def test_les_ingredients_qui_nomment_l_aliment_rejoignent_ses_refs():
    groups = backfill.group_candidates([row("Cumin moulu", food_key="cumin")])
    backfill.ingredient_refs(groups, ["cumin", "cumin en poudre", "carotte"])
    assert groups[0]["refs"] == ["cumin moulu", "cumin", "cumin en poudre"]

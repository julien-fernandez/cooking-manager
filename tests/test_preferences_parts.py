"""La part d'une convive est un repas de SA rotation, pas un repas du foyer (#172)."""

from cooking_manager.preferences import check_preferences, families_in, load_rules

ROTATE = {"kind": "rotate", "target": "famille de proteine", "value": 6, "unit": "repas",
          "scope": "week", "person": "", "reason": ""}


def meal(dish, ingredients, parts=None):
    return {"day": "mercredi", "slot": "dinner", "dish": dish,
            "ingredients": ingredients, "parts": parts or {}}


POULET_COLIN = meal(
    "Poulet citron-origan sur plaque, pommes de terre et brocolis (+ colin pour Claire)",
    ["haut de cuisse de poulet", "pomme de terre", "brocoli"],
    {"Claire": ["filet de colin"]})


def rotate(meals, **overrides):
    [check] = check_preferences(meals, load_rules([{**ROTATE, **overrides}]))
    return check


def test_le_plat_du_foyer_ne_compte_pas_la_part():
    assert "poisson" not in families_in(POULET_COLIN)
    assert families_in(POULET_COLIN, "Claire").count("poisson") == 1


def test_la_part_compte_dans_la_rotation_de_sa_convive():
    check = rotate([POULET_COLIN])
    assert "poisson" not in check.by_family
    assert check.parts_by_family == {"Claire": {"poisson": 1}}


def test_le_menu_du_05_10_ne_depasse_plus_avec_les_parts():
    """Cinq repas de poisson pour le foyer, trois parts de Claire : 8 se lisait « breached »."""
    fish = [meal(f"Cabillaud {i}", ["cabillaud"]) for i in range(5)]
    parts = [meal(f"Viande {i} (+ thon pour Claire)", ["boeuf hache"],
                  {"Claire": ["thon"]}) for i in range(3)]
    check = rotate(fish + parts)
    assert check.by_family["poisson"] == 5
    assert check.parts_by_family["Claire"]["poisson"] == 3
    assert check.breached is False


def test_le_titre_seul_ne_fait_pas_compter_la_part():
    no_data = meal("Bolognaise (+ thon pour Claire)", ["boeuf hache"])
    assert "poisson" not in families_in(no_data)


def test_une_regle_de_la_convive_voit_sa_part():
    check = rotate([POULET_COLIN], person="Claire")
    assert check.by_family.get("poisson") == 1


def test_une_regle_du_foyer_ne_voit_pas_la_part():
    [check] = check_preferences([POULET_COLIN], load_rules([
        {"kind": "maximize", "target": "colin", "value": 1, "unit": "repas", "scope": "week",
         "person": "Julien", "reason": ""}]))
    assert check.hits == []


def test_dorade_et_bar_sont_des_poissons():
    """Le menu du 05/10 posait une dorade, le répertoire un bar au four : la rotation ne les comptait pas."""
    assert families_in(meal("Dorade au four", ["dorade"])) == ["poisson"]
    assert families_in(meal("Bar au four citron-persil", ["filet de bar"])) == ["poisson"]


def test_parenthese_ordinaire_conservee():
    plain = meal("Salade (thon, maïs)", [])
    assert "poisson" in families_in(plain)

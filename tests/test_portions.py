"""Une recette se ramène à la tablée réelle : restes comptés, part = une portion — ADR 0041."""

from cooking_manager.parts import eaters_by_meal, portions

CLAIRE = 3
JULIEN = 1


def ing(position, name, qty, **kw):
    return {"position": position, "name": name, "raw": f"{qty} g {name}",
            "qty_min": qty, "qty_max": qty, "unit": "g",
            "for_person_id": kw.get("for_person_id"),
            "replaces_position": kw.get("replaces_position")}


MAFE = [
    ing(1, "poulet", 1200),
    ing(2, "crevettes", 120, for_person_id=CLAIRE, replaces_position=1),
    ing(3, "riz", 800),
]


def qty(lines, name):
    found = [line["qty_min"] for line in lines if line["name"] == name]
    return found[0] if found else None


class TestPortions:
    def test_une_ligne_commune_suit_le_nombre_de_portions(self):
        lines = portions([ing(1, "riz", 800)], servings=10, eaters=[1, 2, 3, 4])
        assert qty(lines, "riz") == 320

    def test_une_part_vaut_une_portion_quelle_que_soit_la_taille_de_la_recette(self):
        lines = portions(MAFE, servings=10, eaters=[JULIEN, CLAIRE, 5, 6])
        assert qty(lines, "crevettes") == 120

    def test_la_ligne_remplacee_ne_compte_pas_la_portion_de_celle_qui_ne_la_mange_pas(self):
        lines = portions(MAFE, servings=10, eaters=[JULIEN, CLAIRE, 5, 6])
        assert qty(lines, "poulet") == 1200 * 3 / 10
        assert qty(lines, "riz") == 800 * 4 / 10

    def test_une_part_compte_autant_de_portions_que_de_repas_de_sa_convive(self):
        lines = portions(MAFE, servings=10, eaters=[JULIEN, CLAIRE, CLAIRE])
        assert qty(lines, "crevettes") == 240
        assert qty(lines, "poulet") == 1200 * 1 / 10

    def test_une_part_de_quelqu_un_d_absent_ne_s_achete_pas(self):
        lines = portions(MAFE, servings=10, eaters=[JULIEN, 5])
        assert qty(lines, "crevettes") is None
        assert qty(lines, "poulet") == 1200 * 2 / 10

    def test_des_couverts_imposes_priment_sur_la_tablee(self):
        lines = portions([ing(1, "riz", 800)], servings=4, eaters=[1, 2], covers=4)
        assert qty(lines, "riz") == 800

    def test_une_ligne_sans_quantite_reste_sans_quantite(self):
        lines = portions([{**ing(1, "sel", None), "raw": "sel"}], servings=4, eaters=[1, 2])
        assert lines[0]["qty_min"] is None

    def test_une_colonne_non_chargee_leve(self):
        import pytest

        from cooking_manager.parts import ColumnNotLoaded
        with pytest.raises(ColumnNotLoaded):
            portions([{"position": 1, "name": "riz", "qty_min": 1}], servings=4, eaters=[1])


class TestMealPortions:
    def test_un_dejeuner_a_deux_se_cuisine_pour_deux(self):
        from cooking_manager.parts import meal_portions
        meals = [{"id": 10, "leftovers_of": None, "covers": None,
                  "present": ["Julien", "Claire"]}]
        assert meal_portions(meals) == {10: 2}

    def test_les_restes_du_lendemain_s_ajoutent_au_plat_du_jour(self):
        from cooking_manager.parts import meal_portions
        meals = [
            {"id": 10, "leftovers_of": None, "covers": None,
             "present": ["Julien", "Claire", "Lou", "Tom"]},
            {"id": 11, "leftovers_of": 10, "covers": None, "present": ["Claire"]},
        ]
        assert meal_portions(meals) == {10: 5}

    def test_des_couverts_poses_a_la_main_priment_et_les_restes_s_y_ajoutent(self):
        from cooking_manager.parts import meal_portions
        meals = [
            {"id": 10, "leftovers_of": None, "covers": 6, "present": ["Julien"]},
            {"id": 11, "leftovers_of": 10, "covers": None, "present": ["Claire"]},
        ]
        assert meal_portions(meals) == {10: 7}

    def test_une_tablee_inconnue_ne_rend_pas_de_portions(self):
        from cooking_manager.parts import meal_portions
        meals = [{"id": 10, "leftovers_of": None, "covers": None, "present": []}]
        assert meal_portions(meals) == {}


class TestEatersByMeal:
    def test_les_mangeurs_d_un_reste_s_ajoutent_au_plat_source(self):
        meals = [
            {"id": 10, "leftovers_of": None, "present": ["Julien", "Claire", "Lou", "Tom"]},
            {"id": 11, "leftovers_of": 10, "present": ["Claire"]},
        ]
        assert eaters_by_meal(meals)[10] == ["Julien", "Claire", "Lou", "Tom", "Claire"]

    def test_un_reste_n_a_pas_de_mangeurs_a_lui(self):
        meals = [
            {"id": 10, "leftovers_of": None, "present": ["Julien"]},
            {"id": 11, "leftovers_of": 10, "present": ["Claire"]},
        ]
        assert 11 not in eaters_by_meal(meals)

    def test_un_reste_sans_source_ne_s_ajoute_a_rien(self):
        meals = [
            {"id": 10, "leftovers_of": None, "present": ["Julien"]},
            {"id": 11, "leftovers_of": None, "present": ["Claire"], "leftovers": True},
        ]
        assert eaters_by_meal(meals) == {10: ["Julien"]}

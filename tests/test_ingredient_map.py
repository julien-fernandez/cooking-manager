"""Vue par recette : chaque ingrédient, son aliment, son stock, son panier."""

from cooking_manager.ingredient_map import build_ingredient_map


def _recipe(slug, title, *ingredients, day="2026-10-06", slot="lunch"):
    return {"recipe_slug": slug, "title": title, "day": day, "slot": slot,
            "photo_url": f"/media/recipes/{slug}.jpg", "ingredients": list(ingredients)}


def _ing(name, food_key=None, raw=None):
    return {"name": name, "name_normalized": name, "raw": raw or name, "food_key": food_key}


def _line(name, outcome="absent", recipes=(), merged_from=(), purchase=True, qty=100.0,
          unit="g", pantry=None, reason=""):
    return {"name": name, "name_normalized": name, "outcome": outcome, "recipes": list(recipes),
            "merged_from": list(merged_from), "purchase": {"kind": "buy"} if purchase else None,
            "qty": qty, "unit": unit, "pantry": pantry, "reason": reason}


def _only(result, recipe_index=0, ingredient_index=0):
    return result["recipes"][recipe_index]["ingredients"][ingredient_index]


class TestLien:
    def test_un_ingredient_rattache_est_linked(self):
        result = build_ingredient_map(
            [_recipe("a", "A", _ing("lait", "lait"))], [_line("lait", recipes=["A"])], {}, set())
        assert _only(result)["link"] == "linked"

    def test_un_ingredient_sans_cle_est_unlinked_et_a_relire(self):
        result = build_ingredient_map(
            [_recipe("a", "A", _ing("lait"))], [_line("lait", recipes=["A"])], {}, set())
        item = _only(result)
        assert item["link"] == "unlinked"
        assert item["review"] is True
        assert "unlinked" in item["reasons"]

    def test_un_nom_refuse_avec_motif_n_est_pas_unlinked(self):
        result = build_ingredient_map(
            [_recipe("a", "A", _ing("eau gazeuse"))],
            [_line("eau gazeuse", recipes=["A"], outcome="suffisant", purchase=False)],
            {}, {"eau gazeuse"})
        item = _only(result)
        assert item["link"] == "refused"
        assert "unlinked" not in item["reasons"]


class TestLigneDeCourses:
    def test_un_ingredient_fusionne_retrouve_sa_ligne(self):
        """« filet de poulet » est absorbé par « poulet » : il garde le verdict de la ligne fusionnée."""
        recipe = _recipe("a", "A", _ing("filet de poulet", "poulet"))
        line = _line("poulet", recipes=["A"], merged_from=["filet de poulet"], qty=500.0)
        item = _only(build_ingredient_map([recipe], [line], {}, set()))
        assert item["stock"]["outcome"] == "absent"
        assert item["menu_qty"] == 500.0

    def test_un_ingredient_hors_achat_n_est_pas_a_relire(self):
        """L'eau n'a aucune ligne (NON_PURCHASE) : « hors achats », pas un doute."""
        item = _only(build_ingredient_map([_recipe("a", "A", _ing("eau"))], [], {}, set()))
        assert item["stock"] is None
        assert item["review"] is False

    def test_le_stock_porte_la_ligne_retenue(self):
        pantry = {"name": "lait demi-ecreme", "qty_text": "1 L", "status": "ok"}
        line = _line("lait", outcome="inconnu", recipes=["A"], pantry=pantry, reason="quantité ?")
        item = _only(build_ingredient_map([_recipe("a", "A", _ing("lait", "lait"))], [line], {}, set()))
        assert item["stock"] == {"outcome": "inconnu", "reason": "quantité ?", "pantry": pantry}
        assert "stock_unknown" in item["reasons"]


class TestPanier:
    def test_un_panier_illisible_n_est_pas_un_panier_vide(self):
        result = build_ingredient_map(
            [_recipe("a", "A", _ing("lait", "lait"))], [_line("lait", recipes=["A"])], None, set())
        assert _only(result)["cart"] is None
        assert "cart_problem" not in _only(result)["reasons"]

    def test_le_verdict_du_panier_vient_de_verify(self):
        entry = {"food": "lait", "verdict": "decide_a_la_main", "reason": "dose", "cart": 2.0,
                 "unit": "l", "labels": ["Lait 1L"]}
        result = build_ingredient_map(
            [_recipe("a", "A", _ing("lait", "lait"))], [_line("lait", recipes=["A"])],
            {"lait": entry}, set())
        item = _only(result)
        assert item["cart"] == {"verdict": "decide_a_la_main", "reason": "dose", "qty": 2.0,
                                "unit": "l", "labels": ["Lait 1L"]}
        assert "decided_by_hand" in item["reasons"]

    def test_un_besoin_qui_manque_au_panier_se_relit(self):
        entry = {"food": "lait", "verdict": "MANQUE", "reason": "", "cart": 0.0, "unit": "ml",
                 "labels": []}
        result = build_ingredient_map(
            [_recipe("a", "A", _ing("lait", "lait"))], [_line("lait", recipes=["A"])],
            {"lait": entry}, set())
        assert "cart_problem" in _only(result)["reasons"]

    def test_un_verdict_ok_ne_se_relit_pas(self):
        entry = {"food": "lait", "verdict": "ok", "reason": "", "cart": 1000.0, "unit": "ml",
                 "labels": ["Lait"]}
        line = _line("lait", outcome="absent", recipes=["A"])
        item = _only(build_ingredient_map(
            [_recipe("a", "A", _ing("lait", "lait"))], [line], {"lait": entry}, set()))
        assert item["review"] is False


class TestPartage:
    def test_shared_with_exclut_la_recette_elle_meme(self):
        line = _line("lait", recipes=["A", "B"])
        result = build_ingredient_map(
            [_recipe("a", "A", _ing("lait", "lait")), _recipe("b", "B", _ing("lait", "lait"))],
            [line], {}, set())
        assert _only(result, 0)["shared_with"] == ["B"]
        assert _only(result, 1)["shared_with"] == ["A"]

    def test_une_recette_servie_deux_fois_n_a_qu_une_section(self):
        recipe = _recipe("a", "A", _ing("lait", "lait"))
        result = build_ingredient_map([recipe, recipe], [_line("lait", recipes=["A"])], {}, set())
        assert len(result["recipes"]) == 1


class TestCompteurs:
    def test_to_review_se_lit_avant_recipes(self):
        result = build_ingredient_map([], [], {}, set())
        assert list(result)[:2] == ["to_review", "recipes"]

    def test_les_compteurs_comptent_lignes_et_aliments(self):
        recipes = [_recipe("a", "A", _ing("lait")), _recipe("b", "B", _ing("lait"))]
        result = build_ingredient_map(recipes, [_line("lait", recipes=["A", "B"])], {}, set())
        assert result["to_review"]["rows"] == 2
        assert result["to_review"]["foods"] == 1
        assert result["to_review"]["unlinked"] == 2

    def test_une_recette_sans_ingredient_ne_leve_pas(self):
        result = build_ingredient_map([_recipe("a", "A")], [], {}, set())
        assert result["recipes"][0]["ingredients"] == []
        assert result["to_review"]["rows"] == 0


class TestRevueFinale:
    def test_deux_lignes_de_meme_nom_gardent_le_doute(self):
        """« beurre » en g et en cs : deux lignes ; la plus douteuse l'emporte, aucune n'est perdue."""
        lignes = [_line("beurre", outcome="suffisant", recipes=["A"], qty=50.0),
                  _line("beurre", outcome="inconnu", recipes=["B"], qty=1.0, unit="cs")]
        result = build_ingredient_map(
            [_recipe("a", "A", _ing("beurre", "beurre")), _recipe("b", "B", _ing("beurre", "beurre"))],
            lignes, {}, set())
        assert _only(result, 0)["stock"]["outcome"] == "inconnu"
        assert _only(result, 0)["shared_with"] == ["B"]
        assert _only(result, 1)["shared_with"] == ["A"]

    def test_le_panier_se_lit_par_l_aliment_de_la_ligne_hote(self):
        """verify juge « poulet » ; « filet de poulet » (fusionné) hérite de ce verdict."""
        entry = {"food": "poulet", "verdict": "MANQUE", "reason": "", "cart": 0.0, "unit": "g",
                 "labels": []}
        recipes = [_recipe("a", "A", _ing("filet de poulet", "poulet-filet")),
                   _recipe("b", "B", _ing("poulet", "poulet"))]
        line = _line("poulet", recipes=["A", "B"], merged_from=["filet de poulet"])
        result = build_ingredient_map(recipes, [line], {"poulet": entry}, set())
        assert _only(result, 0)["cart"]["verdict"] == "MANQUE"
        assert "cart_problem" in _only(result, 0)["reasons"]

    def test_un_ingredient_lie_sans_ligne_se_relit(self):
        """Une substitution a pu retirer la ligne : le silence ne vaut pas « tout va bien »."""
        item = _only(build_ingredient_map([_recipe("a", "A", _ing("lait", "lait"))], [], {}, set()))
        assert item["review"] is True
        assert "no_line" in item["reasons"]

    def test_un_nom_normalise_vide_est_renormalise(self):
        ing = {"name": "Lait", "name_normalized": "", "raw": "Lait", "food_key": "lait"}
        result = build_ingredient_map([_recipe("a", "A", ing)], [_line("lait", recipes=["A"])], {}, set())
        assert _only(result)["stock"] is not None


def _staple_line(name, outcome, *, staple, declared=True):
    return {"name_normalized": name, "outcome": outcome, "reason": "", "qty": 1.0, "unit": "c.c.",
            "pantry": None, "recipes": ["Dahl"], "merged_from": [], "pantry_staple": staple,
            "declared": declared}


def _dahl(*names):
    return [{"recipe_slug": "dahl", "title": "Dahl", "photo_url": None, "day": None, "slot": "dinner",
             "ingredients": [{"name": n, "name_normalized": n, "raw": f"1 c.c. {n}", "food_key": n}
                             for n in names]}]


def test_les_basiques_vont_dans_leur_groupe_et_ne_sont_pas_a_relire():
    lines = [_staple_line("lentille", "suffisant", staple=False),
             _staple_line("cumin", "placard", staple=True),
             _staple_line("curcuma", "placard", staple=True, declared=False),
             _staple_line("sel", "absent", staple=True)]
    built = build_ingredient_map(_dahl("lentille", "cumin", "curcuma", "sel"), lines, None, set())
    [recipe] = built["recipes"]
    assert [i["name"] for i in recipe["ingredients"]] == ["lentille"]
    assert [(b["name"], b["state"]) for b in recipe["pantry_basics"]] == [
        ("cumin", "au_placard"), ("curcuma", "jamais_declare"), ("sel", "fini")]
    assert built["to_review"]["rows"] == 0


def test_un_basique_fini_garde_son_controle_du_panier():
    """Un basique déclaré fini s'achète comme un autre : MANQUE au panier se relit."""
    entry = {"food": "sel", "verdict": "MANQUE", "reason": "", "cart": 0.0, "unit": "g",
             "labels": []}
    built = build_ingredient_map(_dahl("sel"), [_staple_line("sel", "absent", staple=True)],
                                 {"sel": entry}, set())
    [basic] = built["recipes"][0]["pantry_basics"]
    assert basic["state"] == "fini" and basic["cart"]["verdict"] == "MANQUE"
    assert "cart_problem" in basic["reasons"]
    assert built["to_review"]["cart_problem"] == 1


def test_un_placard_ne_masque_pas_une_ligne_douteuse_du_meme_nom():
    """Huile : 2 c.s. au placard et 400 ml mesurés incomparables — le doute passe devant."""
    lines = [_staple_line("huile olive", "placard", staple=True),
             {**_staple_line("huile olive", "inconnu", staple=False), "unit": "ml", "qty": 400.0}]
    built = build_ingredient_map(_dahl("huile olive"), lines, None, set())
    recipe = built["recipes"][0]
    assert recipe["pantry_basics"] == []
    assert recipe["ingredients"][0]["stock"]["outcome"] == "inconnu"

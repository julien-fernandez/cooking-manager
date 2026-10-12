"""Un basique du placard couvre toute dose tant qu'une ligne vit (ADR 0043)."""

from datetime import date

from cooking_manager.pantry import (
    MISSING, STAPLE, Need, Pantry, PantryItem, build_needs, check_need, check_needs,
    staple_rule_applies, staples_undeclared, staples_unlinked)

TODAY = date(2026, 10, 6)
SPICES = "Épices & Herbes"


def line(name, *, food_key, status="ok", qty_text="", qty_value=None, unit=None, rayon=SPICES):
    return PantryItem(rayon=rayon, name=name, name_normalized=name.lower(), qty_text=qty_text,
                      qty_value=qty_value, unit=unit, status=status, entered_at=TODAY,
                      food_key=food_key)


def need(name, qty=None, unit=None, food_key=None):
    return Need(name=name, name_normalized=name, qty=qty, unit=unit, food_key=food_key)


def pantry(*items, staples=("cumin", "huile olive", "sel")):
    return Pantry(items=list(items), updated=TODAY, staples=frozenset(staples))


def test_present_sans_quantite_couvre_toute_dose():
    verdict = check_need(need("cumin", 2, "c.c.", "cumin"), pantry(line("Cumin", food_key="cumin")), TODAY)
    assert (verdict.outcome, verdict.reason, verdict.to_buy, verdict.declared) == (
        STAPLE, "au placard", 0.0, True)


def test_stock_faible_reste_au_placard():
    verdict = check_need(need("cumin", 1, "c.c.", "cumin"),
                         pantry(line("Cumin", food_key="cumin", status="low")), TODAY)
    assert verdict.outcome == STAPLE


def test_une_ligne_vivante_suffit_meme_a_cote_d_une_ligne_finie():
    p = pantry(line("Cumin moulu", food_key="cumin", status="out"), line("Cumin", food_key="cumin"))
    assert check_need(need("cumin", 1, "c.c.", "cumin"), p, TODAY).outcome == STAPLE


def test_toutes_les_lignes_finies_font_acheter():
    p = pantry(line("Cumin", food_key="cumin", status="out"))
    assert check_need(need("cumin", 1, "c.c.", "cumin"), p, TODAY).outcome == MISSING


def test_jamais_declare_est_suppose_present_mais_le_dit():
    verdict = check_need(need("cumin", 1, "c.c.", "cumin"), pantry(), TODAY)
    assert (verdict.outcome, verdict.declared, verdict.pantry_item) == (STAPLE, False, None)
    assert verdict.reason == "jamais déclaré au garde-manger"


def test_sans_quantite_dans_la_recette():
    verdict = check_need(need("sel", None, None, "sel"), pantry(line("Sel", food_key="sel")), TODAY)
    assert verdict.outcome == STAPLE


def test_dose_sous_le_seuil_reste_au_placard():
    verdict = check_need(need("huile olive", 250, "ml", "huile olive"),
                         pantry(line("Huile d'olive", food_key="huile olive")), TODAY)
    assert verdict.outcome == STAPLE


def test_dose_au_dela_du_seuil_est_mesuree_et_le_dit():
    p = pantry(line("Huile d'olive", food_key="huile olive", qty_text="1 bouteille 1 L",
                    qty_value=1.0, unit="l"))
    verdict = check_need(need("huile olive", 400, "ml", "huile olive"), p, TODAY)
    assert verdict.outcome == "suffisant"
    assert verdict.reason.endswith("dose de basique au-delà de 300 ml : mesurée")


def test_le_seuil_se_juge_apres_conversion():
    """0,5 kg de sel pour une croûte = 500 g : mesuré, pas couvert d'office."""
    p = pantry(line("Sel", food_key="sel"))
    verdict = check_need(need("sel", 0.5, "kg", "sel"), p, TODAY)
    assert verdict.outcome != STAPLE


def test_un_aliment_ordinaire_ne_change_pas():
    p = pantry(line("Riz", food_key="riz", qty_text="500 g", qty_value=500, unit="g",
                    rayon="Sec — Féculents & Légumineuses"))
    assert check_need(need("riz", 300, "g", "riz"), p, TODAY).outcome == "suffisant"


def test_un_basique_ne_reserve_rien():
    p = pantry(line("Cumin", food_key="cumin"))
    first, second = check_needs([need("cumin", 1, "c.c.", "cumin"),
                                 need("cumin", 1, "c.c.", "cumin")], p, TODAY)
    assert (first.outcome, second.outcome) == (STAPLE, STAPLE)


def test_jamais_declares_un_par_aliment():
    verdicts = check_needs([need("cumin", 1, "c.c.", "cumin"), need("cumin moulu", 1, "c.c.", "cumin"),
                            need("sel", None, None, "sel")], pantry(line("Sel", food_key="sel")), TODAY)
    assert staples_undeclared(verdicts) == [{"name": "cumin", "food_key": "cumin"}]


def test_un_besoin_sans_aliment_qui_ressemble_a_un_basique_se_signale():
    """Deux recettes aux food_key divergents : build_needs met food_key à None."""
    p = pantry(line("cumin", food_key="cumin"),
               line("paprika fume", food_key=None, rayon=SPICES),
               line("riz", food_key="riz", rayon="Sec — Féculents & Légumineuses"))
    needs = [need("cumin", 1, "c.c."), need("paprika fume", 1, "c.c."), need("riz", 200, "g")]
    assert staples_unlinked(needs, p) == ["cumin", "paprika fume"]


def test_un_basique_qui_perd_son_aliment_a_la_fusion_se_signale_meme_sans_stock():
    """Recette A : cumin rattaché ; recette B : cumin sans aliment ; aucune ligne au garde-manger."""
    needs = build_needs([("A", [{"name": "cumin", "name_normalized": "cumin", "qty_min": 1,
                                 "unit": "c.c.", "food_key": "cumin"}], 1.0),
                         ("B", [{"name": "cumin", "name_normalized": "cumin", "qty_min": 1,
                                 "unit": "c.c."}], 1.0)])
    [merged] = needs
    assert merged.food_key is None
    assert staples_unlinked(needs, pantry()) == ["cumin"]


def test_fini_sur_une_ligne_sans_aliment_fait_acheter():
    """La ligne « Cumin » sans food_key, passée out par PATCH /api/pantry : elle dit le stock."""
    p = pantry(line("Cumin", food_key=None, status="out"))
    verdict = check_need(need("cumin", 1, "c.c.", "cumin"), p, TODAY)
    assert verdict.outcome == MISSING


def test_present_sur_une_ligne_sans_aliment_est_declare():
    p = pantry(line("Cumin", food_key=None))
    verdict = check_need(need("cumin", 1, "c.c.", "cumin"), p, TODAY)
    assert (verdict.outcome, verdict.declared) == (STAPLE, True)


def test_une_ligne_d_un_autre_aliment_ne_declare_pas_le_basique():
    p = pantry(line("Cumin", food_key="carvi"))
    verdict = check_need(need("cumin", 1, "c.c.", "cumin"), p, TODAY)
    assert (verdict.outcome, verdict.declared) == (STAPLE, False)


def test_le_regime_basique_ne_vaut_que_sous_le_seuil():
    p = pantry()
    assert staple_rule_applies(need("sel", 1, "c.c.", "sel"), p)
    assert not staple_rule_applies(need("sel", 0.5, "kg", "sel"), p)
    assert not staple_rule_applies(need("riz", 1, "c.c.", "riz"), p)


def test_seuls_l_eau_et_les_glacons_ne_s_achetent_jamais():
    from cooking_manager.pantry import NON_PURCHASE

    assert not {"sel", "sel fin", "poivre", "poivre noir", "poivre du moulin"} & NON_PURCHASE
    assert {"eau", "glacon"} <= NON_PURCHASE

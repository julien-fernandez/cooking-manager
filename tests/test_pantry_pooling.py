"""Les retraits du panier du 05/10 (#187) : « 3 briques 400 g » se multiplie, deux lignes du même aliment s'additionnent."""

from datetime import date

import pytest

from cooking_manager.pantry import (
    ENOUGH, PARTIAL, UNKNOWN, Need, Pantry, PantryItem, check_need, check_needs, entry_quantity)

TODAY = date(2026, 10, 5)
FRESH = "Frais — Légumes & Fruits"
DRY = "Sec — Conserves & Bocaux"


@pytest.mark.parametrize("text,expected", [
    ("3 briques 400 g", (1200.0, "g")),
    ("2 sachets 900 g", (1800.0, "g")),
    ("14 briques 1 L", (14.0, "l")),
    ("2 paquets 454 g  | 338 kcal", (908.0, "g")),
    ("1 sachet 50 cl", (50.0, "cl")),
    ("1 boîte 150 g net / 130 g égoutté", (150.0, "g")),
    ("2×100 g", (200.0, "g")),
    ("~580 g", (580.0, "g")),
    ("1 botte", (1.0, "botte")),
])
def test_un_contenant_chiffre_se_multiplie(text, expected):
    value, unit, refusal = entry_quantity(text, "ok")
    assert refusal is None
    assert (value, unit) == expected


def item(name, qty_text, *, food_key, section=FRESH, status="ok", entered=TODAY, item_id=None):
    value, unit, _ = entry_quantity(qty_text, status)
    return PantryItem(rayon=section, name=name, name_normalized=name.lower(), qty_text=qty_text,
                      qty_value=value, unit=unit, status=status, entered_at=entered,
                      food_key=food_key, item_id=item_id)


def need(name, qty, unit, food_key):
    return Need(name=name, name_normalized=name, qty=qty, unit=unit, food_key=food_key)


def test_pulpe_de_tomates_du_05_10_suffit():
    pantry = Pantry(items=[item("Pulpe fine de tomates", "3 briques 400 g",
                                food_key="pulpe de tomate", section=DRY)], updated=TODAY)
    verdict = check_need(need("pulpe de tomate", 800, "g", "pulpe de tomate"), pantry, TODAY)
    assert verdict.outcome == ENOUGH


def test_deux_lignes_du_meme_aliment_s_additionnent():
    pantry = Pantry(items=[
        item("Brocoli surgelé", "1 sachet 900 g", food_key="brocoli", section="Surgelés"),
        item("Brocoli", "500 g", food_key="brocoli"),
    ], updated=TODAY)
    verdict = check_need(need("brocoli", 1200, "g", "brocoli"), pantry, TODAY)
    assert verdict.outcome == ENOUGH
    assert verdict.pantry_item is not None
    assert "1 sachet 900 g + 500 g" in verdict.reason


def test_une_ligne_incomparable_rend_la_question_au_lieu_d_acheter():
    """Oignon rouge ~580 g + oignons blancs « 1 botte » : la botte ne se pèse pas, on demande."""
    pantry = Pantry(items=[
        item("Oignon rouge", "~580 g", food_key="oignon"),
        item("Oignons blancs", "1 botte", food_key="oignon"),
    ], updated=TODAY)
    verdict = check_need(need("oignon", 7, "pièce", "oignon"), pantry, TODAY)
    assert verdict.outcome == UNKNOWN
    assert "sans compter Oignons blancs (1 botte), dont la quantité ne se compare pas" in verdict.reason


def test_une_ligne_incomparable_ne_gene_pas_un_stock_suffisant():
    pantry = Pantry(items=[
        item("Oignon rouge", "~580 g", food_key="oignon"),
        item("Oignons blancs", "1 botte", food_key="oignon"),
    ], updated=TODAY)
    assert check_need(need("oignon", 2, "pièce", "oignon"), pantry, TODAY).outcome == ENOUGH


def test_une_ligne_epuisee_ou_perimee_ne_s_additionne_pas():
    pantry = Pantry(items=[
        item("Courgettes", "1 kg", food_key="courgette"),
        item("Courgettes bio", "750 g", food_key="courgette", status="out"),
        item("Courgettes vieilles", "1 kg", food_key="courgette", entered=date(2026, 9, 1)),
    ], updated=TODAY)
    verdict = check_need(need("courgette", 1500, "g", "courgette"), pantry, TODAY)
    assert verdict.outcome == PARTIAL
    assert verdict.to_buy == 500


def test_la_ligne_chiffree_est_preferee_a_une_ligne_sans_quantite():
    pantry = Pantry(items=[
        item("Oignon en flocons", "", food_key="oignon", section="Épices & Herbes"),
        item("Oignon rouge", "~580 g", food_key="oignon"),
    ], updated=TODAY)
    verdict = check_need(need("oignon", 300, "g", "oignon"), pantry, TODAY)
    assert verdict.outcome == ENOUGH
    assert verdict.pantry_item is not None and verdict.pantry_item.name == "Oignon rouge"


def test_la_reservation_porte_sur_le_stock_additionne():
    """Deux repas à 900 g contre 900 g + 500 g : le second n'a plus que 500 g."""
    pantry = Pantry(items=[
        item("Brocoli surgelé", "1 sachet 900 g", food_key="brocoli", section="Surgelés"),
        item("Brocoli", "500 g", food_key="brocoli"),
    ], updated=TODAY)
    first, second = check_needs([need("brocoli", 900, "g", "brocoli"),
                                 need("brocoli", 900, "g", "brocoli")], pantry, TODAY)
    assert first.outcome == ENOUGH
    assert (second.outcome, second.to_buy) == (PARTIAL, 400)


def test_deux_etats_differents_ne_s_additionnent_pas():
    """Menu du 05/10 : 200 g de crevettes cuites + 500 g de crues se comptaient ensemble (#202)."""
    pantry = Pantry(items=[
        item("crevette nordique decortiquee cuite 200g", "1 × 200g", food_key="crevette", section="Surgelés"),
        item("crevette decortiquee crue et deveinee", "500 g", food_key="crevette", section="Surgelés"),
    ], updated=TODAY)
    verdict = check_need(need("crevette decortiquee", 1000, "g", "crevette"), pantry, TODAY)
    assert verdict.outcome == UNKNOWN
    assert verdict.pantry_item is not None
    assert "+" not in (verdict.pantry_item.qty_text or "")
    assert verdict.reason == ("1 × 200g en stock, il en manque — sans compter crevette decortiquee crue "
                              "et deveinee, d'un autre état (cuit ≠ cru) : à confirmer")


def test_un_etat_absent_ne_contredit_pas_un_etat_declare():
    pantry = Pantry(items=[
        item("lentille cuite", "400 g", food_key="lentille", section=DRY),
        item("lentille", "300 g", food_key="lentille", section=DRY),
    ], updated=TODAY)
    assert check_need(need("lentille", 600, "g", "lentille"), pantry, TODAY).outcome == ENOUGH


@pytest.mark.parametrize("first,second", [
    ("tomate sechee", "tomate fraiche"),
    ("saumon fume", "saumon frais"),
    ("myrtille surgelee", "myrtille fraiche"),
])
def test_chaque_axe_d_etat_separe(first, second):
    pantry = Pantry(items=[item(first, "300 g", food_key="x", section=DRY),
                           item(second, "300 g", food_key="x", section=DRY)], updated=TODAY)
    assert check_need(need("x", 500, "g", "x"), pantry, TODAY).outcome == UNKNOWN


def test_une_tete_de_brocoli_se_compare_a_des_sachets():
    """Menu du 05/10 : 1 brocoli face à 2 sachets de 900 g restait « à confirmer »."""
    pantry = Pantry(items=[item("Brocoli surgelé", "2 sachets 900 g", food_key="brocoli", section="Surgelés")],
                    updated=TODAY)
    assert check_need(need("brocoli", 1, "pièce", "brocoli"), pantry, TODAY).outcome == ENOUGH

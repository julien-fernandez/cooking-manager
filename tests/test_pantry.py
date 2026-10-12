"""Unitaires — garde-manger vivant et différentiel."""

from datetime import date, timedelta

import pytest

from cooking_manager.pantry import (
    ENOUGH,
    Pantry,
    PantryItem,
    MISSING,
    PARTIAL,
    UNKNOWN,
    Need,
    build_needs,
    check_need,
    parse_pantry,
)
from cooking_manager.ingredients import Ingredient, normalize_name

VAULT = """---
updated: 2026-07-11
---

# Garde-manger

## Épicerie sèche

- Miel bio (liquide) — 2 pots (entré 2026-06-02) # status=ok
- Sauce soja salée (Drive A) — 1 flacon 250 ml # status=ok
- Farine T65 — 250 g # status=low
- Riz basmati — 0 # status=out

## Frais — Protéines

- Œufs — 6 pièces (entré 2026-07-08) # status=ok
- Filets de poulet — 480 g / 4 filets # status=urgent
"""


def need_of(name, qty=None, unit=None):
    """Un besoin isolé, tel que `build_needs` le produirait."""
    return Need(name=name, name_normalized=normalize_name(name), qty=qty, unit=unit)


@pytest.fixture
def pantry():
    return parse_pantry(VAULT)


class TestParse:
    def test_reads_updated_and_rayons(self, pantry):
        assert pantry.updated == date(2026, 7, 11)
        assert {i.rayon for i in pantry.items} == {"Épicerie sèche", "Frais — Protéines"}

    def test_reads_status_and_quantities(self, pantry):
        farine = pantry.find("farine")
        assert farine is not None
        assert (farine.status, farine.qty_value, farine.unit) == ("low", 250.0, "g")

    def test_ligature_in_name_is_matchable(self, pantry):
        """« Œufs » n'a AUCUNE décomposition Unicode : sans expansion explicite"""
        assert pantry.find("oeufs") is not None

    def test_staleness_is_computed_not_assumed(self, pantry):
        assert pantry.age_days(today=date(2026, 8, 4)) == 24
        assert pantry.is_stale(today=date(2026, 8, 4)) is True
        assert pantry.is_stale(today=date(2026, 7, 12)) is False


class TestMatching:
    def test_containment_match(self, pantry):
        """« miel » doit rencontrer « Miel bio (liquide) » — c'est cet"""
        item = pantry.find("miel")
        assert item is not None and item.status == "ok"

    def test_no_match_returns_none(self, pantry):
        assert pantry.find("cardamome") is None

    def test_partial_word_does_not_match(self, pantry):
        """« ri » ne doit pas matcher « riz » : une inclusion nue transforme"""
        assert pantry.find("ri") is None

    def _stock(self, *names):
        return Pantry(items=[
            PantryItem(rayon="X", name=n, name_normalized=normalize_name(n),
                       qty_text="", status="ok")
            for n in names
        ], updated=None)

    @pytest.mark.parametrize("besoin,attendu", [
        ("mélange mâche et roquette", "Mélange de mâche et roquette"),
        ("bouillon de légumes", "Knorr Bouillon de Légumes"),
        ("origan", "Hello Fresh Origan"),
    ])
    def test_un_mot_outil_ou_une_marque_ne_cassent_pas_l_appariement(self, besoin, attendu):
        """Un seul « de » manquant faisait racheter un sachet déjà au frigo"""
        stock = self._stock("Mélange de mâche et roquette", "Knorr Bouillon de Légumes",
                            "Hello Fresh Origan")
        found = stock.find(normalize_name(besoin))
        assert found is not None and found.name == attendu

    def test_un_alias_tranche_ce_qu_aucune_regle_ne_peut_decider(self):
        """`pantry_alias` existait depuis le 2026-09-01 mais n'était lu par"""
        item = PantryItem(item_id=7, rayon="Épices", name="Hello Fresh Origan",
                          name_normalized=normalize_name("Hello Fresh Origan"))
        besoin = normalize_name("origan séché")
        assert Pantry(items=[item]).find(besoin) is None
        aliased = Pantry(items=[item], aliases={besoin: 7})
        found = aliased.find(besoin)
        assert found is not None and found.name == "Hello Fresh Origan"

    @pytest.mark.parametrize("besoin", ["lait de coco", "crème fraîche", "huile de sésame"])
    def test_le_besoin_plus_precis_ne_se_satisfait_pas_du_generique(self, besoin):
        """Le stock peut être plus précis que le besoin, jamais l'inverse : un"""
        stock = self._stock("Lait entier", "Crème liquide", "Huile d'olive")
        assert stock.find(normalize_name(besoin)) is None

    @pytest.mark.parametrize("besoin,stock", [
        ("pâte d'arachide", "Pâtes"),
        ("beurre", "Beurre de cacahuète"),
        ("lait", "Lait de coco brique"),
    ])
    def test_un_complement_fait_un_autre_aliment_dans_le_stock(self, besoin, stock):
        """« pâte d'arachide » ≠ « Pâtes », « beurre » ≠ « Beurre de cacahuète » (2026-10-05)."""
        assert self._stock(stock).find(normalize_name(besoin)) is None

    @pytest.mark.parametrize("besoin,stock", [
        ("lait", "Lait entier"),
        ("beurre", "Beurre doux"),
        ("fromage blanc", "Fromage blanc 3.2% MG"),
    ])
    def test_une_qualite_reste_le_meme_aliment_dans_le_stock(self, besoin, stock):
        found = self._stock(stock).find(normalize_name(besoin))
        assert found is not None and found.name == stock


class TestVerdicts:
    def test_enough_when_stock_covers(self, pantry):
        need = need_of("miel", 1.0, "c.s.")
        assert check_need(need, pantry).outcome == ENOUGH

    def test_missing_when_absent(self, pantry):
        need = need_of("cardamome", 200.0, "g")
        v = check_need(need, pantry)
        assert v.outcome == MISSING and v.pantry_item is None

    def test_missing_when_status_out(self, pantry):
        need = need_of("riz basmati", 300.0, "g")
        assert check_need(need, pantry).outcome == MISSING

    def test_partial_when_stock_is_short(self, pantry):
        need = need_of("farine T65", 500.0, "g")
        v = check_need(need, pantry)
        assert v.outcome == PARTIAL
        assert v.to_buy == 250.0

    def test_unknown_when_units_are_incommensurable(self, pantry):
        """« 3 filets » contre « 480 g » : on ne convertit pas, on demande."""
        need = need_of("filets de poulet", 3.0, "pièce")
        assert check_need(need, pantry).outcome == UNKNOWN

    def test_quantityless_need_on_stocked_item_is_enough(self, pantry):
        """« sauce soja » sans quantité chiffrée, sur un flacon en stock :"""
        need = need_of("sauce soja")
        assert check_need(need, pantry).outcome == ENOUGH


class TestStaleness:
    def test_fresh_is_assumed_gone_when_inventory_is_old(self, pantry):
        """Inventaire vieux de 24 jours → le frais est supposé épuisé. La"""
        need = need_of("œufs", 4.0, "pièce")
        v = check_need(need, pantry, today=date(2026, 8, 4))
        assert v.outcome in (MISSING, UNKNOWN)
        assert v.assumed_empty

    def test_dry_goods_survive_a_stale_inventory(self, pantry):
        """Le sec ne périme pas : la règle d'ancienneté ne s'y applique pas."""
        need = need_of("miel", 1.0, "c.s.")
        assert check_need(need, pantry, today=date(2026, 8, 4)).outcome == ENOUGH

    def test_fresh_is_trusted_when_inventory_is_recent(self, pantry):
        need = need_of("œufs", 4.0, "pièce")
        assert check_need(need, pantry, today=date(2026, 7, 12)).outcome == ENOUGH


class TestAggregation:
    def test_same_ingredient_across_recipes_is_summed(self):
        """Deux recettes qui veulent des œufs produisent UNE ligne, avec les"""
        needs = build_needs([
            ("Gratin", [Ingredient(raw="2 œufs", name="œufs", qty_min=2.0, unit="pièce", position=1)], 1.0),
            ("Cookies", [Ingredient(raw="3 œufs", name="œufs", qty_min=3.0, unit="pièce", position=1)], 1.0),
        ])
        assert len(needs) == 1
        assert needs[0].qty == 5.0
        assert set(needs[0].recipes) == {"Gratin", "Cookies"}

    def test_portions_ratio_scales_quantities(self):
        needs = build_needs([
            ("Gratin", [Ingredient(raw="400 g pommes de terre", name="pommes de terre",
                                   qty_min=400.0, unit="g", position=1)], 1.5),
        ])
        assert needs[0].qty == 600.0

    def test_incommensurable_units_stay_separate(self):
        """« 2 pièces » et « 200 g » de courgette ne s'additionnent pas — les"""
        needs = build_needs([
            ("A", [Ingredient(raw="2 kiwis", name="kiwis", qty_min=2.0, unit="pièce", position=1)], 1.0),
            ("B", [Ingredient(raw="200 g kiwis", name="kiwis", qty_min=200.0, unit="g", position=1)], 1.0),
        ])
        assert len(needs) == 2

    def test_same_family_different_units_convert_before_summing(self):
        """« 800 g » + « 1 kg » du même aliment font 1,8 kg, pas 801."""
        needs = build_needs([
            ("Saumon", [Ingredient(raw="800 g patates douces", name="patates douces",
                                   qty_min=800.0, unit="g", position=1)], 1.0),
            ("Pilons", [Ingredient(raw="1 kg patates douces", name="patates douces",
                                   qty_min=1.0, unit="kg", position=1)], 1.0),
        ])
        assert len(needs) == 1
        assert (needs[0].qty, needs[0].unit) == (1800.0, "g")

    def test_range_takes_the_upper_bound(self):
        """« 2–3 c.s. » : on achète pour 3. Manquer coûte plus cher qu'avoir"""
        needs = build_needs([
            ("A", [Ingredient(raw="2–3 c.s. miel", name="miel",
                              qty_min=2.0, qty_max=3.0, unit="c.s.", position=1)], 1.0),
        ])
        assert needs[0].qty == 3.0


class TestNeedConsolidation:
    """Deux libellés d'un même aliment font UN besoin (#81)."""

    def test_a_qualifier_merges_into_the_generic_name(self):
        needs = build_needs([
            ("Risotto", [Ingredient(raw="1 l bouillon de légumes", name="bouillon de légumes",
                                    qty_min=1.0, unit="l", position=1)], 1.0),
            ("Dahl", [Ingredient(raw="1 l bouillon de légumes chaud", name="bouillon de légumes chaud",
                                 qty_min=1.0, unit="l", position=1)], 1.0),
        ])
        assert len(needs) == 1
        assert needs[0].name_normalized == "bouillon de legume"
        assert needs[0].qty == 2000.0
        assert "bouillon de légumes chaud" in needs[0].merged_from

    def test_the_founding_case_lentils(self):
        """Le cas qui faisait racheter : le stock porte « lentilles vertes »,"""
        needs = build_needs([
            ("Salade", [Ingredient(raw="300 g lentilles vertes", name="lentilles vertes",
                                   qty_min=300.0, unit="g", position=1)], 1.0),
            ("Poêlée", [Ingredient(raw="300 g lentilles vertes sèches", name="lentilles vertes sèches",
                                   qty_min=300.0, unit="g", position=1)], 1.0),
        ])
        assert len(needs) == 1
        assert needs[0].name_normalized == "lentille verte"

    def test_incommensurable_units_are_never_merged(self):
        """« 2 sachets » et « 2 pièces » de mâche restent deux besoins : les"""
        needs = build_needs([
            ("A", [Ingredient(raw="2 sachets mélange mâche et roquette",
                              name="mélange mâche et roquette", qty_min=2.0, unit="sachet", position=1)], 1.0),
            ("B", [Ingredient(raw="2 poignées de mâche et roquette",
                              name="poignée de mâche et roquette", qty_min=2.0, unit="pièce", position=1)], 1.0),
        ])
        assert len(needs) == 2

    def test_two_varieties_stay_apart(self):
        """« lentilles corail » et « lentilles vertes » ne sont pas le même"""
        needs = build_needs([
            ("A", [Ingredient(raw="300 g lentilles corail", name="lentilles corail",
                              qty_min=300.0, unit="g", position=1)], 1.0),
            ("B", [Ingredient(raw="300 g lentilles vertes", name="lentilles vertes",
                              qty_min=300.0, unit="g", position=1)], 1.0),
        ])
        assert len(needs) == 2

    @pytest.mark.parametrize("generique,complement", [
        ("lait", "lait de coco"),
        ("beurre", "beurre de cacahuète"),
    ])
    def test_a_complement_is_another_food_and_never_merges(self, generique, complement):
        """« lait de coco » se disait couvert par 14 L de lait de vache (2026-10-05)."""
        needs = build_needs([
            ("A", [Ingredient(raw=f"200 ml {generique}", name=generique,
                              qty_min=200.0, unit="ml", position=1)], 1.0),
            ("B", [Ingredient(raw=f"200 ml {complement}", name=complement,
                              qty_min=200.0, unit="ml", position=1)], 1.0),
        ])
        assert len(needs) == 2
        assert all(not n.merged_from for n in needs)

    @pytest.mark.parametrize("aliment,transforme", [
        ("lentilles corail", "pâtes de lentilles corail"),
        ("pois chiches", "farine de pois chiches"),
        ("amandes", "lait d'amande"),
    ])
    def test_a_processed_form_is_another_food(self, aliment, transforme):
        """Menu du 05/10 : 320 g de pâtes de lentilles s'achetaient en 20 g de lentilles."""
        needs = build_needs([
            ("A", [Ingredient(raw=f"200 g {aliment}", name=aliment,
                              qty_min=200.0, unit="g", position=1)], 1.0),
            ("B", [Ingredient(raw=f"320 g {transforme}", name=transforme,
                              qty_min=320.0, unit="g", position=1)], 1.0),
        ])
        assert len(needs) == 2

    def test_lemon_juice_still_buys_lemons(self):
        needs = build_needs([
            ("A", [Ingredient(raw="2 citrons", name="citrons", qty_min=2.0, unit="pièce",
                              position=1)], 1.0),
            ("B", [Ingredient(raw="1 jus de citron", name="jus de citron", qty_min=1.0,
                              unit="pièce", position=1)], 1.0),
        ])
        assert len(needs) == 1

    def test_a_quality_still_merges_into_the_generic(self):
        needs = build_needs([
            ("A", [Ingredient(raw="500 g fromage blanc", name="fromage blanc",
                              qty_min=500.0, unit="g", position=1)], 1.0),
            ("B", [Ingredient(raw="500 g fromage blanc entier", name="fromage blanc entier",
                              qty_min=500.0, unit="g", position=1)], 1.0),
        ])
        assert len(needs) == 1
        assert needs[0].qty == 1000.0

    def test_a_partial_overlap_is_left_alone(self):
        """« trio de poivrons en lanières » et « poivrons en lanières (rouge et"""
        needs = build_needs([
            ("A", [Ingredient(raw="600 g poivrons en lanières", name="poivrons en lanières",
                              qty_min=600.0, unit="g", position=1)], 1.0),
            ("B", [Ingredient(raw="600 g trio de poivrons en lanières", name="trio de poivrons en lanières",
                              qty_min=600.0, unit="g", position=1)], 1.0),
            ("C", [Ingredient(raw="2 poivrons rouges", name="poivrons rouges",
                              qty_min=2.0, unit="pièce", position=1)], 1.0),
        ])
        assert len(needs) == 2
        merged = [n for n in needs if n.unit == "g"][0]
        assert merged.name_normalized == "poivron en laniere"
        assert merged.qty == 1200.0

    def test_recipes_and_requirement_survive_the_merge(self):
        """Une recette qui EXIGE l'ingrédient l'emporte sur une qui le rend"""
        needs = build_needs([
            ("A", [Ingredient(raw="10 g persil", name="persil", qty_min=10.0,
                              unit="g", is_optional=True, position=1)], 1.0),
            ("B", [Ingredient(raw="10 g persil plat", name="persil plat", qty_min=10.0,
                              unit="g", position=1)], 1.0),
        ])
        assert len(needs) == 1
        assert needs[0].is_optional is False
        assert set(needs[0].recipes) == {"A", "B"}


class TestFoundingBug:
    """Non-régression du 2026-08-04 : sauce soja et miel étaient au"""

    @pytest.mark.parametrize("name,unit,qty", [
        ("miel", "c.s.", 2.0),
        ("sauce soja", "c.s.", 3.0),
    ])
    def test_stocked_condiments_never_reach_the_shopping_list(self, pantry, name, unit, qty):
        need = need_of(name, qty, unit)
        v = check_need(need, pantry, today=date(2026, 8, 4))
        assert v.outcome == ENOUGH, f"{name} repart en courses — le bug est revenu"
        assert v.pantry_item is not None

    def test_the_inventory_age_does_not_silently_flush_the_pantry(self, pantry):
        """Le garde-fou du garde-fou : la règle d'ancienneté ne doit pas"""
        old = parse_pantry(VAULT.replace("2026-07-11", "2025-01-01"))
        need = need_of("miel", 2.0, "c.s.")
        assert check_need(need, old, today=date(2026, 8, 4)).outcome == ENOUGH


class TestRealVault:
    """Contrôle de volume du parser contre le vrai fichier."""

    def test_real_file_parses_completely(self):
        from pathlib import Path
        path = Path(r"C:\\vault\Noyau\Cuisine\Garde-manger.md")
        if not path.exists():
            pytest.skip("vault local indisponible")
        p = parse_pantry(path.read_text(encoding="utf-8"))
        assert len(p.items) > 200
        assert p.updated is not None
        age = p.age_days()
        assert age is not None and age >= 0
        assert p.is_stale(today=p.updated + timedelta(days=15)) is True


class TestBulkPayload:
    """Un lot de courses porte sa date d'entrée réelle et sa provenance."""

    def test_a_batch_carries_its_real_entry_date_and_source(self):
        from backend.app import PantryBulkItem
        item = PantryBulkItem.model_validate({
            "name": "Feta grecque AOP 200g",
            "section": "Frais — Protéines",
            "qty_text": "2 barquettes 200 g",
            "entered_at": "2026-09-08",
            "source": "drive",
        })
        assert item.entered_at == date(2026, 9, 8)
        assert item.source == "drive"

    def test_the_voice_payload_keeps_working_without_the_new_fields(self):
        from backend.app import PantryBulkItem
        item = PantryBulkItem(name="Concombre")
        assert item.entered_at is None
        assert item.source == "voice"


class TestNonPurchaseExclusion:
    """#80 — l'eau du robinet et le sel ne sont pas des achats."""

    def test_eau_is_excluded(self):
        meals = [("Soupe", [{"name": "eau", "name_normalized": "eau",
                             "qty_min": 1.0, "unit": "l", "parsed": True}], 1.0)]
        needs = build_needs(meals)
        assert not any(n.name_normalized == "eau" for n in needs)

    def test_sel_is_a_staple_need_not_excluded(self):
        """ADR 0043 : le sel est un basique du placard (verdict `placard`), plus une exclusion figée."""
        meals = [("Riz", [{"name": "Sel", "name_normalized": "sel",
                           "qty_min": 5.0, "unit": "g", "parsed": True}], 1.0)]
        needs = build_needs(meals)
        assert any(n.name_normalized == "sel" for n in needs)

    def test_normal_ingredient_kept(self):
        meals = [("Riz", [{"name": "Riz basmati", "name_normalized": "riz basmati",
                           "qty_min": 300.0, "unit": "g", "parsed": True}], 1.0)]
        needs = build_needs(meals)
        assert any(n.name_normalized == "riz basmati" for n in needs)


class TestPerItemFreshness:
    """#84 — un frais périmé le reste même si un autre article vient d'être touché."""

    def test_old_perishable_is_unknown_even_when_global_is_fresh(self):
        today = date(2026, 9, 10)
        old_item = PantryItem(
            rayon="Frais \u2014 L\u00e9gumes", name="Courgette",
            name_normalized="courgette", qty_text="3", qty_value=3, unit="pi\u00e8ce",
            status="ok", entered_at=date(2026, 8, 1),
        )
        pantry = Pantry(items=[old_item], updated=today)
        assert not pantry.is_stale(today)
        need = Need(name="Courgette", name_normalized="courgette",
                    qty=2.0, unit="pi\u00e8ce")
        v = check_need(need, pantry, today=today)
        assert v.outcome == "inconnu"
        assert v.assumed_empty

    def test_fresh_perishable_is_enough(self):
        today = date(2026, 9, 10)
        fresh_item = PantryItem(
            rayon="Frais \u2014 L\u00e9gumes", name="Courgette",
            name_normalized="courgette", qty_text="3", qty_value=3, unit="pi\u00e8ce",
            status="ok", entered_at=date(2026, 9, 8),
        )
        pantry = Pantry(items=[fresh_item], updated=today)
        need = Need(name="Courgette", name_normalized="courgette",
                    qty=2.0, unit="pi\u00e8ce")
        v = check_need(need, pantry, today=today)
        assert v.outcome == "suffisant"

    def test_perishable_without_entered_at_is_unknown(self):
        today = date(2026, 9, 10)
        no_date_item = PantryItem(
            rayon="Frais \u2014 Prot\u00e9ines", name="Poulet",
            name_normalized="poulet", qty_text="500 g", qty_value=500, unit="g",
            status="ok", entered_at=None,
        )
        pantry = Pantry(items=[no_date_item], updated=today)
        need = Need(name="Poulet", name_normalized="poulet",
                    qty=400.0, unit="g")
        v = check_need(need, pantry, today=today)
        assert v.outcome == "inconnu"
        assert v.assumed_empty


class TestPerishableSection:
    """Refs #119 : le test portait sur le NOM du rayon, pas sur l'aliment."""

    def test_a_fresh_section_is_perishable(self):
        from cooking_manager.pantry import is_perishable_section
        assert is_perishable_section("Frais — Légumes & Fruits")
        assert is_perishable_section("Frais — Protéines")

    def test_a_dry_section_never_is_even_when_it_says_fruit(self):
        from cooking_manager.pantry import is_perishable_section
        assert not is_perishable_section("Sec — Fruits Secs & Graines")
        assert not is_perishable_section("Sec — Protéines & Compléments")

    def test_a_section_without_a_hint_is_not_perishable(self):
        from cooking_manager.pantry import is_perishable_section
        assert not is_perishable_section("Condiments & Huiles")
        assert not is_perishable_section("Surgelés")
        assert not is_perishable_section("")


class TestUneLigneDeStockNeSertQuUneFois:
    """Cabillaud de lundi et de dimanche, 800 g chacun, contre un seul paquet de 800 g (2026-10-05)."""

    @staticmethod
    def _cabillaud():
        return Pantry(items=[PantryItem(
            rayon="Surgelés", name="DRIVE_A Filet de cabillaud 4 pièces 800g",
            name_normalized="drive_a filet de cabillaud 4 piece 800g",
            qty_text="1 × 800g", qty_value=800.0, unit="g", item_id=8619)])

    def test_le_second_besoin_ne_revoit_pas_les_grammes_du_premier(self):
        from cooking_manager.pantry import check_needs

        lundi = need_of("cabillaud", 800.0, "g")
        dimanche = need_of("filet de cabillaud", 800.0, "g")
        premier, second = check_needs([lundi, dimanche], self._cabillaud())

        assert premier.outcome == ENOUGH
        assert second.outcome == PARTIAL
        assert second.to_buy == 800.0
        assert "réservé" in second.reason

    def test_un_besoin_seul_garde_son_verdict(self):
        from cooking_manager.pantry import check_needs

        (seul,) = check_needs([need_of("cabillaud", 500.0, "g")], self._cabillaud())
        assert seul.outcome == ENOUGH


class TestLeBesoinTientDansUneUnite:
    """Courgettes du 05/10 : « 6,75 pièce + g » sans total, et 1 kg de stock jamais retranché."""

    @staticmethod
    def _stock(name, qty_text, qty, unit):
        return Pantry(items=[PantryItem(
            rayon="Épicerie", name=name, name_normalized=normalize_name(name),
            qty_text=qty_text, qty_value=qty, unit=unit)])

    @staticmethod
    def _courgettes():
        def line(qty, unit):
            return {"name": "courgette", "name_normalized": "courgette", "qty_min": qty,
                    "unit": unit}
        return build_needs([("A", [line(500, "g"), line(3.75, "pièce")], 1.0),
                            ("B", [line(3, "pièce"), line(1, "kg")], 1.0)])

    def test_pieces_et_grammes_font_un_seul_besoin(self):
        (need,) = self._courgettes()
        assert (need.qty, need.unit) == (3187.5, "g")
        assert need.estimate is not None and "poids estimé" in need.estimate

    def test_un_kilo_en_stock_se_retranche(self):
        from cooking_manager.pantry import check_needs

        (need,) = self._courgettes()
        (verdict,) = check_needs([need], self._stock("courgette", "1 kg", 1.0, "kg"))
        assert verdict.outcome == PARTIAL
        assert verdict.to_buy == 2187.5
        assert "poids estimé" in verdict.reason

    def test_un_besoin_en_pieces_se_compare_a_un_stock_en_grammes(self):
        oignon = self._stock("oignon", "580 g", 580.0, "g")
        verdict = check_need(need_of("oignon", 7.0, "pièce"), oignon)
        assert verdict.outcome == PARTIAL
        assert verdict.to_buy == 3.13
        assert "poids estimé" in verdict.reason

    def test_trois_tetes_d_ail_couvrent_quatre_gousses(self):
        verdict = check_need(need_of("ail", 4.0, "gousse"),
                             self._stock("ail", "3 têtes", 3.0, "tête"))
        assert verdict.outcome == ENOUGH
        assert "estimé" in verdict.reason

    def test_sans_poids_typique_le_stock_en_grammes_reste_inconnu(self):
        verdict = check_need(need_of("kiwi", 3.0, "pièce"),
                             self._stock("kiwi", "500 g", 500.0, "g"))
        assert verdict.outcome == UNKNOWN

    def test_un_stock_deja_pris_par_un_besoin_en_pieces_ne_sert_pas_deux_fois(self):
        from cooking_manager.pantry import check_needs

        stock = self._stock("oignon", "1 kg", 1000.0, "g")
        premier, second = check_needs(
            [need_of("oignon", 4.0, "pièce"), need_of("oignon", 4.0, "pièce")], stock)
        assert premier.outcome == ENOUGH
        assert second.outcome == PARTIAL
        assert second.to_buy == 1.33

    def test_une_unite_identique_hors_table_se_compare_sans_rien_estimer(self):
        stock = self._stock("sauce", "3 boîtes", 3.0, "boîte")
        verdict = check_need(need_of("sauce", 2.0, "boîte"), stock)
        assert verdict.outcome == ENOUGH
        assert "estimé" not in verdict.reason

    def test_une_unite_identique_insuffisante_dit_ce_qui_manque(self):
        stock = self._stock("ail", "3 gousses", 3.0, "gousse")
        verdict = check_need(need_of("ail", 4.0, "gousse"), stock)
        assert (verdict.outcome, verdict.to_buy) == (PARTIAL, 1.0)
        assert "estimé" not in verdict.reason

    def test_trois_tetes_lues_par_le_parseur_couvrent_quatre_gousses(self):
        from cooking_manager.pantry import entry_quantity

        value, unit, refusal = entry_quantity("3 têtes", "ok")
        assert (value, unit, refusal) == (3.0, "tête", None)
        verdict = check_need(need_of("ail", 4.0, "gousse"),
                             self._stock("ail", "3 têtes", value, unit))
        assert verdict.outcome == ENOUGH
        assert "équivalent estimé" in verdict.reason


class TestLeGardeMangerSApparieParLAliment:
    """« pâte d'arachide » lue absente alors que « Pur beurre de cacahuète » était au placard (05/10)."""

    @staticmethod
    def _placard(food_key):
        name = "Pur beurre de cacahuète"
        return Pantry(items=[PantryItem(
            rayon="Épicerie", name=name, name_normalized=normalize_name(name),
            qty_text="350 g", qty_value=350.0, unit="g", food_key=food_key)])

    def test_la_food_key_trouve_l_item_sans_alias(self):
        item = self._placard("beurre de cacahuete").find(
            normalize_name("pâte d'arachide"), "beurre de cacahuete")
        assert item is not None and item.name == "Pur beurre de cacahuète"

    def test_sans_food_key_le_nom_seul_decide(self):
        assert self._placard("beurre de cacahuete").find(normalize_name("pâte d'arachide")) is None

    def test_une_food_key_que_personne_ne_porte_retombe_sur_le_nom(self):
        placard = self._placard("beurre de cacahuete")
        assert placard.find(normalize_name("pur beurre de cacahuète"), "autre") is not None
        assert placard.find(normalize_name("pâte d'arachide"), "autre") is None

    def test_entre_lignes_du_meme_aliment_la_mieux_dotee_gagne(self):
        placard = self._placard("beurre de cacahuete")
        placard.items.append(PantryItem(
            rayon="Épicerie", name="Beurre d'arachide", name_normalized="beurre arachide",
            status="out", food_key="beurre de cacahuete"))
        item = placard.find("pate arachide", "beurre de cacahuete")
        assert item is not None and item.status == "ok"

    def test_le_besoin_porte_la_food_key_et_le_verdict_trouve_le_stock(self):
        (need,) = build_needs([("A", [{
            "name": "pâte d'arachide", "name_normalized": "pate arachide",
            "qty_min": 100, "unit": "g", "food_key": "beurre de cacahuete"}], 1.0)])
        assert need.food_key == "beurre de cacahuete"
        verdict = check_need(need, self._placard("beurre de cacahuete"))
        assert verdict.outcome != MISSING

    def test_deux_besoins_d_aliments_differents_perdent_la_food_key(self):
        def line(name, key):
            return {"name": name, "name_normalized": name, "qty_min": 1, "unit": "g",
                    "food_key": key}
        (need,) = build_needs([("A", [line("lait", "lait"), line("lait entier", "lait entier")], 1.0)])
        assert need.food_key is None

    def test_la_food_key_cherche_le_poids_typique(self):
        def line(qty, unit):
            return {"name": "courgettes vertes", "name_normalized": "courgette vert",
                    "qty_min": qty, "unit": unit, "food_key": "courgette"}
        (need,) = build_needs([("A", [line(500, "g"), line(2, "pièce")], 1.0)])
        assert (need.qty, need.unit) == (1000.0, "g")
        assert need.estimate is not None and "poids estimé" in need.estimate


class TestCompositeNeverCovers:
    """Un produit composé ne couvre pas l'ingrédient nommé dans son libellé (#203)."""

    @staticmethod
    def stock(name, food_key=None):
        return Pantry(items=[PantryItem(rayon="Sec — Conserves & Bocaux", name=name,
                                        name_normalized=normalize_name(name), qty_text="1 pot",
                                        qty_value=1.0, unit="pot", food_key=food_key)])

    def test_une_ligne_rattachee_a_un_autre_aliment_ne_couvre_pas_par_son_nom(self):
        pantry = self.stock("CASSEGRAIN Poivrons cuisinés au piment d'Espelette 375g", "poivron")
        assert pantry.find("piment d'Espelette", "piment espelette") is None
        assert pantry.find("piment d'Espelette") is None

    def test_une_ligne_rattachee_couvre_un_besoin_qui_nomme_son_aliment(self):
        pantry = self.stock("Cumin moulu Ducros", "cumin")
        assert pantry.find("cumin moulu") is not None

    @pytest.mark.parametrize("besoin,produit", [
        ("piment d'Espelette", "Poivrons cuisinés au piment d'Espelette"),
        ("chocolat", "Pain au chocolat"),
        ("huile d'olive", "Thon à l'huile d'olive"),
        ("vanille", "Glace aux graines de vanille"),
    ])
    def test_un_aliment_qui_parfume_un_produit_n_est_pas_ce_produit(self, besoin, produit):
        assert self.stock(produit).find(besoin) is None

    @pytest.mark.parametrize("besoin,produit", [
        ("crème", "Danette crème dessert chocolat"),
        ("chocolat", "Gâteau chocolat"),
        ("potiron", "Velouté potiron"),
    ])
    def test_un_plat_ne_couvre_pas_son_ingredient(self, besoin, produit):
        assert self.stock(produit).find(besoin) is None

    @pytest.mark.parametrize("besoin,produit", [
        ("crème", "Crème légère Elle & Vire"),
        ("thon", "Thon albacore Petit Navire"),
        ("chocolat", "Chocolat noir dessert"),
        ("Épices au choix : cumin, herbes de Provence", "Herbes de Provence"),
        ("gâteau", "Gâteau chocolat"),
    ])
    def test_le_produit_lui_meme_reste_couvert(self, besoin, produit):
        assert self.stock(produit).find(besoin) is not None

from cooking_manager.verification import (
    MISSING,
    OFF_APP,
    OFF_MENU_ASSUMED,
    OK,
    STOCK_INCOMPARABLE,
    SURPLUS,
    UNMEASURABLE,
    DECIDED_BY_HAND,
    CartLine,
    Need,
    index_cart_rows,
    lines_stock_unknown,
    covered_by_stock_for,
    lines_to_buy,
    stock_question,
    stock_question_for,
    unreadable,
    verify,
)

READ_AT = "2026-09-24T18:02"


def judged(result, food):
    return next(e for e in result["per_food"] if e["food"] == food)


class TestLesQuatreVerdictsDu21Septembre:
    """Les quatre lignes de l'exemple de #157 sont les quatre pannes réelles de ce jour-là."""

    RESULT = verify(
        [Need("oeuf", 26, "piece", pack_size=6),
         Need("poivron", 1150, "g", pack_size=500),
         Need("courgette", 400, "g", pack_size=500)],
        [CartLine("Oeufs x12", food="oeuf", qty=12, unit="piece", origin="menu"),
         CartLine("Poivrons 1,2 kg", food="poivron", qty=1200, unit="g", origin="menu"),
         CartLine("Courgettes 2 kg", food="courgette", qty=2000, unit="g", origin="menu"),
         CartLine("Cabillaud 800 g", food="cabillaud", qty=800, unit="g",
                  origin="manual")],
        READ_AT)

    def test_un_repas_sans_son_ingredient_bloque(self):
        assert judged(self.RESULT, "oeuf")["verdict"] == MISSING

    def test_la_quantite_juste_a_un_contenant_pres_passe(self):
        assert judged(self.RESULT, "poivron")["verdict"] == OK

    def test_au_dela_d_un_contenant_de_trop_avertit(self):
        courgette = judged(self.RESULT, "courgette")
        assert courgette["verdict"] == SURPLUS
        assert "contenant" in courgette["reason"]

    def test_une_ligne_posee_a_la_main_est_un_hors_menu_assume(self):
        assert judged(self.RESULT, "cabillaud")["verdict"] == OFF_MENU_ASSUMED

    def test_le_verdict_global_est_faux_et_nomme_ses_bloquants(self):
        assert self.RESULT["ok"] is False
        assert "oeuf" in self.RESULT["reason"]
        assert [e["food"] for e in self.RESULT["blocking"]] == ["oeuf"]


class TestUnPanierConformeConclut:
    def test_tout_au_compte_rend_ok(self):
        result = verify([Need("carotte", 1000, "g", pack_size=1000)],
                        [CartLine("Carottes 1 kg", food="carotte", qty=1000, unit="g",
                                  origin="menu")], READ_AT)
        assert result["ok"] is True
        assert result["measured"] is True
        assert result["counts"] == {OK: 1}


class TestCeQuiNAPasEteRegarde:
    """Un panier illisible ne vaut jamais un panier conforme."""

    def test_une_lecture_impossible_n_est_jamais_ok(self):
        result = unreadable("session anonyme")
        assert result["ok"] is False
        assert result["measured"] is False
        assert "session anonyme" in result["reason"]
        assert result["per_food"] == []

    def test_un_contenant_inconnu_chez_le_drive_ne_conclut_pas(self):
        result = verify([Need("farine", 1000, "g", pack_size=1000)],
                        [CartLine("Farine", food="farine", qty=None, unit=None,
                                  origin="menu")], READ_AT)
        assert judged(result, "farine")["verdict"] == UNMEASURABLE
        assert result["ok"] is False

    def test_des_unites_incomparables_ne_concluent_pas(self):
        result = verify([Need("lait", 2000, "ml", pack_size=1000)],
                        [CartLine("Lait 2 kg", food="lait", qty=2000, unit="g",
                                  origin="menu")], READ_AT)
        assert judged(result, "lait")["verdict"] == UNMEASURABLE

    def test_un_surplus_sans_contenant_connu_se_lit_comme_non_mesurable(self):
        """`surplus_measurable: false` : le silence se lit, il ne passe pas pour un surplus nul."""
        result = verify([Need("sel", 100, "g", pack_size=None)],
                        [CartLine("Sel 110 g", food="sel", qty=110, unit="g",
                                  origin="menu")], READ_AT)
        sel = judged(result, "sel")
        assert sel["verdict"] == OK
        assert sel["surplus_measurable"] is False


class TestSaisiHorsDeLApplication:
    def test_une_ligne_du_drive_qu_aucune_ligne_de_l_appli_ne_porte_bloque(self):
        result = verify([], [CartLine("Chips 150 g", food=None, qty=150, unit="g")],
                        READ_AT)
        entry = result["per_food"][0]
        assert entry["verdict"] == OFF_APP
        assert result["ok"] is False

    def test_un_aliment_hors_menu_non_assume_bloque(self):
        """La ligne existe dans l'appli mais vient du menu : rien ne l'assume hors menu."""
        result = verify([], [CartLine("Saumon 400 g", food="saumon", qty=400, unit="g",
                                      origin="menu")], READ_AT)
        assert judged(result, "saumon")["verdict"] == OFF_APP


class TestLesSixPaquetsDeParmesan:
    """#113 : la ligne ajoutée en 6 exemplaires le 20/09 doit se voir AVANT la commande."""

    def test_six_paquets_pour_un_besoin_d_un_seul_sont_un_surplus(self):
        result = verify([Need("parmesan", 100, "g", pack_size=100)],
                        [CartLine("Parmesan râpé 100 g", food="parmesan", qty=600,
                                  unit="g", origin="menu")], READ_AT)
        parmesan = judged(result, "parmesan")
        assert parmesan["verdict"] == SURPLUS
        assert parmesan["cart"] == 600
        assert parmesan["need"] == 100

    def test_les_carottes_manquantes_bloquent_la_meme_commande(self):
        """L'autre retour du 20/09 : « il manque des carottes ? » — la question devient un verdict."""
        result = verify([Need("carotte", 1000, "g", pack_size=1000)], [], READ_AT)
        assert judged(result, "carotte")["verdict"] == MISSING
        assert result["ok"] is False


class TestUnZeroEstUneMesure:
    def test_un_aliment_absent_du_panier_manque_il_n_est_pas_non_mesurable(self):
        """Zéro ligne chez le drive se compare : 0 g contre 1000 g, c'est un MANQUE."""
        result = verify([Need("carotte", 1000, "g", pack_size=1000)], [], READ_AT)
        carotte = judged(result, "carotte")
        assert carotte["verdict"] == MISSING
        assert carotte["cart"] == 0


def shopping_line(name, outcome, qty=None, unit=None, assumed_empty=False, purchase=True):
    buy = {"kind": "mesure", "qty": qty, "unit": unit} if purchase else None
    return {"name": name, "name_normalized": name, "outcome": outcome,
            "assumed_empty": assumed_empty, "purchase": buy}


class TestLeStockCouvreCeQueLePanierNeDoitPasContenir:
    """`purchase` d'une ligne suffisante portait TOUT le besoin : verify la rendait MANQUE."""

    def test_une_ligne_suffisante_n_est_pas_a_acheter(self):
        lines = [shopping_line("flocon avoine", "suffisant", 360, "g")]
        assert lines_to_buy(lines) == []

    def test_une_ligne_presente_mais_incomparable_n_est_pas_a_acheter(self):
        lines = [shopping_line("riz basmati", "inconnu", 1190, "g")]
        assert lines_to_buy(lines) == []

    def test_un_absent_un_insuffisant_et_un_frais_suppose_epuise_s_achetent(self):
        lines = [
            shopping_line("oeuf", "absent", 27, "pièce"),
            shopping_line("beurre", "insuffisant", 40, "g"),
            shopping_line("ail", "inconnu", 11, "gousse", assumed_empty=True),
        ]
        assert [line["name"] for line in lines_to_buy(lines)] == ["oeuf", "beurre", "ail"]

    def test_une_ligne_sans_quantite_commandable_n_est_pas_verifiable(self):
        assert lines_to_buy([shopping_line("curcuma", "absent", purchase=False)]) == []


class TestIndexCartRows:
    def rows(self):
        return [
            {"id": 45, "drive_a_id": "C1", "status": "skipped", "food_key": None},
            {"id": 10, "drive_a_id": "C1", "status": "pushed", "food_key": "fromage blanc"},
            {"id": 9, "drive_a_id": "C1", "status": "skipped", "food_key": None},
        ]

    def test_une_ligne_skipped_ne_masque_pas_la_ligne_vivante(self):
        assert index_cart_rows(self.rows())["C1"]["id"] == 10

    def test_l_ordre_de_lecture_ne_change_rien(self):
        assert index_cart_rows(self.rows()[::-1])["C1"]["id"] == 10

    def test_une_ligne_skipped_seule_ne_revendique_rien(self):
        assert index_cart_rows([self.rows()[0]]) == {}


class TestLeStockIncomparableEstUnBesoinReel:
    """`inconnu` = stock présent, quantité incomparable : « aucun repas ne le réclame » mentait."""

    def test_une_ligne_inconnue_est_listee_a_part(self):
        lines = [shopping_line("riz basmati", "inconnu", 1190, "g"),
                 shopping_line("oeuf", "absent", 27, "pièce")]
        assert [ln["name"] for ln in lines_stock_unknown(lines)] == ["riz basmati"]

    def test_une_ligne_sans_quantite_commandable_n_est_pas_listee(self):
        lines = [shopping_line("curcuma", "inconnu", purchase=False)]
        assert lines_stock_unknown(lines) == []

    def test_le_panier_d_un_besoin_inconnu_n_est_plus_hors_appli_ni_bloquant(self):
        need = Need("riz basmati", 1190.0, "g", stock_unknown=True)
        result = verify([need], [CartLine("Riz basmati 1kg", "riz basmati", 1000.0, "g")], "t")
        assert result["per_food"][0]["verdict"] == STOCK_INCOMPARABLE
        assert result["ok"] is True

    def test_sans_panier_le_besoin_inconnu_se_lit_toujours_et_ne_bloque_pas(self):
        result = verify([Need("riz basmati", 1190.0, "g", stock_unknown=True)], [], "t")
        assert result["per_food"][0]["verdict"] == STOCK_INCOMPARABLE
        assert result["blocking"] == []


class TestUnProduitChoisiSansQuantiteAConfronter:
    """Une dose ou une pièce face à un pot en grammes : le choix est humain, pas mesurable."""

    def test_un_besoin_sans_quantite_avec_un_produit_au_panier_est_decide_a_la_main(self):
        result = verify([Need("aneth", None, "conditionnement")],
                        [CartLine("Aneth 13g", food="aneth", qty=13, unit="g", origin="menu")],
                        READ_AT)
        assert judged(result, "aneth")["verdict"] == DECIDED_BY_HAND
        assert result["ok"] is True

    def test_un_besoin_sans_quantite_et_sans_produit_reste_bloquant(self):
        result = verify([Need("pain complet", None, "tranche")], [], READ_AT)
        assert judged(result, "pain complet")["verdict"] == UNMEASURABLE
        assert result["ok"] is False

    def test_une_piece_face_a_des_grammes_est_decidee_a_la_main(self):
        result = verify([Need("coriandre", 1, "pièce")],
                        [CartLine("Coriandre 11g", food="coriandre", qty=11, unit="g",
                                  origin="menu")], READ_AT)
        assert judged(result, "coriandre")["verdict"] == DECIDED_BY_HAND

    def test_des_grammes_face_a_des_millilitres_restent_incomparables(self):
        result = verify([Need("lait", 2000, "ml")],
                        [CartLine("Lait 2 kg", food="lait", qty=2000, unit="g", origin="menu")],
                        READ_AT)
        assert judged(result, "lait")["verdict"] == UNMEASURABLE


class TestUnAchatRecurrentNeBloquePas:
    """Compote, fromage à tartiner, avocat : des habitudes déclarées, qu'aucun repas ne nomme (2026-10-05)."""

    def test_une_ligne_recurrente_de_l_appli_est_assumee(self):
        result = verify([], [CartLine("Compote de pomme 730g", food="compote sans sucre",
                                      qty=730, unit="g", origin="recurrent")], READ_AT)
        assert judged(result, "compote sans sucre")["verdict"] == OFF_MENU_ASSUMED
        assert result["ok"]

    def test_un_ajout_recurrent_hors_appli_est_assume(self):
        result = verify([], [CartLine("Avocat affiné", origin="recurrent")], READ_AT)
        assert judged(result, "?Avocat affiné")["verdict"] == OFF_MENU_ASSUMED

    def test_un_ajout_qui_n_est_pas_une_habitude_bloque_toujours(self):
        result = verify([], [CartLine("Courgettes")], READ_AT)
        assert judged(result, "?Courgettes")["verdict"] == OFF_APP and not result["ok"]


class TestLePainSAcheteHorsDrive:
    def test_un_besoin_hors_drive_ne_bloque_pas_le_panier(self):
        from cooking_manager.verification import OFF_DRIVE

        result = verify([Need("pain complet", None, "tranche", off_drive=True)], [], READ_AT)
        assert judged(result, "pain complet")["verdict"] == OFF_DRIVE
        assert result["ok"]


class TestDeuxNomsDuMemeAlimentSAdditionnent:
    def test_le_colin_de_vendredi_et_le_lieu_de_samedi(self):
        result = verify([Need("lieu noir", 450, "g", pack_size=600),
                         Need("lieu noir", 600, "g", pack_size=600)],
                        [CartLine("Filet de colin lieu 600g", food="lieu noir", qty=600, unit="g")],
                        READ_AT)
        entry = judged(result, "lieu noir")
        assert (entry["verdict"], entry["need"]) == (MISSING, 1050)


class TestLesPiecesSeJugentEnGrammes:
    """Un besoin en pièces face à un panier en grammes se juge au poids typique (#181)."""

    def test_six_pilons_contre_900_g_sont_ok(self):
        result = verify([Need("pilon poulet", 6, "piece")],
                        [CartLine("Pilons 900 g", food="pilon poulet", qty=900, unit="g",
                                  origin="menu")], READ_AT)
        pilons = judged(result, "pilon poulet")
        assert pilons["verdict"] == OK
        assert "poids estimé" in pilons["reason"]

    def test_trois_tomates_contre_300_g_manquent(self):
        result = verify([Need("tomate", 3, "pièce")],
                        [CartLine("Tomates 300 g", food="tomate", qty=300, unit="g",
                                  origin="menu")], READ_AT)
        tomate = judged(result, "tomate")
        assert tomate["verdict"] == MISSING
        assert "3 pièces × 150 g" in tomate["reason"]

    def test_une_seule_piece_s_ecrit_au_singulier(self):
        result = verify([Need("tomate", 1, "pièce")],
                        [CartLine("Tomates 300 g", food="tomate", qty=300, unit="g",
                                  origin="menu")], READ_AT)
        assert "1 pièce × 150 g" in judged(result, "tomate")["reason"]

    def test_un_aliment_sans_poids_typique_reste_a_decider_a_la_main(self):
        result = verify([Need("concombre", 2, "piece")],
                        [CartLine("Concombre 500 g", food="concombre", qty=500, unit="g",
                                  origin="menu")], READ_AT)
        assert judged(result, "concombre")["verdict"] == DECIDED_BY_HAND


class TestLeSurplusSeMesureSurLePoidsSansContenant:
    """#186 : sans contenant connu, un panier très au-dessus du besoin n'est plus un `ok` muet."""

    @staticmethod
    def _courgette(cart_g, need_g=2000):
        return judged(verify([Need("courgette", need_g, "g")],
                             [CartLine("Courgettes", food="courgette", qty=cart_g, unit="g")],
                             READ_AT), "courgette")

    def test_le_cas_du_5_octobre_pieces_et_grammes_en_surplus(self):
        result = verify(
            [Need("courgette", 2187.5, "g")],
            [CartLine("Courgette france 1 pièce", food="courgette", qty=10, unit="pièce", origin="menu"),
             CartLine("Courgettes france 750g", food="courgette", qty=750, unit="g", origin="manual")],
            READ_AT)
        courgette = judged(result, "courgette")
        assert courgette["verdict"] == SURPLUS
        assert courgette["cart"] == 3250
        assert "+48.6 %" in courgette["reason"]
        assert "poids estimé" in courgette["reason"]
        assert result["ok"] is True

    def test_la_quantite_exacte_passe(self):
        assert self._courgette(2000)["verdict"] == OK

    def test_vingt_pour_cent_de_plus_passe(self):
        assert self._courgette(2400)["verdict"] == OK

    def test_trente_trois_pour_cent_de_plus_avertit(self):
        assert self._courgette(3000)["verdict"] == SURPLUS

    def test_deux_besoins_en_g_et_en_pieces_se_somment_en_g(self):
        result = verify([Need("courgette", 500, "g"), Need("courgette", 2, "pièce")],
                        [CartLine("Courgettes 1 kg", food="courgette", qty=1000, unit="g")], READ_AT)
        courgette = judged(result, "courgette")
        assert courgette["need"] == 1000
        assert courgette["unit"] == "g"
        assert courgette["verdict"] == OK
        assert "poids estimé" in courgette["reason"]

    def test_un_aliment_sans_poids_typique_reste_non_chiffre(self):
        result = verify([Need("xyz", 500, "g"), Need("xyz", 2, "pièce")],
                        [CartLine("Xyz", food="xyz", qty=1, unit="g")], READ_AT)
        assert judged(result, "xyz")["verdict"] == DECIDED_BY_HAND

    def test_une_ligne_illisible_apres_un_changement_d_unite_reste_non_mesurable(self):
        result = verify([Need("courgette", 1000, "g")],
                        [CartLine("A", food="courgette", qty=500, unit="g"),
                         CartLine("B", food="courgette", qty=2, unit="pièce"),
                         CartLine("C", food="courgette", qty=None, unit="g")], READ_AT)
        assert judged(result, "courgette")["verdict"] == UNMEASURABLE

    def test_le_poids_estime_n_est_dit_qu_une_fois_et_pas_pour_les_kg(self):
        mixte = judged(verify([Need("courgette", 6, "pièce")],
                              [CartLine("A", food="courgette", qty=2, unit="pièce"),
                               CartLine("B", food="courgette", qty=500, unit="g")], READ_AT),
                       "courgette")
        assert mixte["reason"].count("poids estimé du panier") == 1
        kilos = judged(verify([Need("courgette", 1000, "g")],
                              [CartLine("A", food="courgette", qty=1, unit="kg"),
                               CartLine("B", food="courgette", qty=500, unit="g")], READ_AT),
                       "courgette")
        assert "poids estimé" not in kilos["reason"]

    def test_un_besoin_en_pieces_en_surplus_se_juge_sur_le_poids(self):
        entry = judged(verify([Need("courgette", 4, "pièce")],
                              [CartLine("A", food="courgette", qty=2000, unit="g")], READ_AT),
                       "courgette")
        assert entry["verdict"] == SURPLUS
        assert entry["surplus_measurable"] is True
        assert "jugé sur le poids" in entry["reason"]
        assert "poids estimé" in entry["reason"]

    def test_un_besoin_nul_ne_divise_pas_par_zero(self):
        entry = judged(verify([Need("sel", 0, "g")],
                              [CartLine("Sel 1 kg", food="sel", qty=1000, unit="g")], READ_AT), "sel")
        assert entry["verdict"] == OK


def riz_en_stock(outcome="inconnu", assumed_empty=False):
    line = shopping_line("riz basmati", outcome, 550, "g", assumed_empty=assumed_empty)
    return {**line, "qty": 550, "unit": "g",
            "pantry": {"name": "riz", "qty_text": "1 paquet", "status": "ok"}}


class TestUnStockIncomparableSeDemande:
    """#187 : 13 lignes `inconnu` achetées dans le doute (« 2 boîtes », « 14 briques »)."""

    def test_la_question_cite_le_stock_et_le_besoin(self):
        question = stock_question(riz_en_stock()) or ""
        assert "1 paquet" in question and "550 g" in question and "riz basmati" in question

    def test_un_frais_suppose_epuise_ne_pose_aucune_question(self):
        assert stock_question(riz_en_stock(assumed_empty=True)) is None

    def test_un_stock_insuffisant_ne_pose_aucune_question(self):
        assert stock_question(riz_en_stock("insuffisant")) is None

    def test_la_ligne_se_trouve_par_food_key_puis_par_nom(self):
        lines = [riz_en_stock()]
        assert stock_question_for(lines, food_key="riz", requested="riz",
                                  keys={"riz basmati": "riz"})
        assert stock_question_for(lines, food_key=None, requested="Riz basmati", keys={})
        assert stock_question_for(lines, food_key="pates", requested="pâtes",
                                  keys={"riz basmati": "riz"}) is None

    def test_une_ligne_trouvee_par_food_key_ne_retombe_pas_sur_le_nom(self):
        couverte = {**riz_en_stock("suffisant"), "name_normalized": "riz thai"}
        lines = [couverte, riz_en_stock()]
        assert stock_question_for(lines, food_key="riz", requested="riz basmati",
                                  keys={"riz thai": "riz"}) is None


class TestUnAlimentCouvertParLeStock:
    """Une ligne suffisante porte pourtant un `purchase` (tout le besoin) : on lit `outcome`."""

    KEYS = {"riz basmati": "riz"}

    def covered(self, *lines, food_key: str | None = "riz", requested="riz", keys=None):
        return covered_by_stock_for(lines, food_key=food_key, requested=requested,
                                    keys=self.KEYS if keys is None else keys)

    def test_suffisant_avec_achat_est_couvert(self):
        line = shopping_line("riz basmati", "suffisant", 550, "g")
        assert line["purchase"]
        assert self.covered(line)
        assert self.covered(line, food_key=None, requested="Riz basmati", keys={})

    def test_insuffisant_manque_et_inconnu_ne_sont_pas_couverts(self):
        for outcome in ("insuffisant", "manque", "inconnu"):
            assert not self.covered(shopping_line("riz basmati", outcome, 550, "g"))

    def test_suppose_epuise_n_est_pas_couvert(self):
        assert not self.covered(shopping_line("riz basmati", "suffisant", 550, "g", assumed_empty=True))

    def test_aliment_absent_de_la_liste_n_est_pas_couvert(self):
        assert not self.covered(shopping_line("riz basmati", "suffisant", 550, "g"),
                                food_key="pates", requested="pâtes")

    def test_une_seule_ligne_a_acheter_suffit_a_ne_pas_couvrir(self):
        lines = [shopping_line("ail", "suffisant", 2, "gousse"),
                 shopping_line("ail poudre", "manque", 10, "g")]
        assert not self.covered(*lines, food_key="ail", requested="ail",
                                keys={"ail": "ail", "ail poudre": "ail"})

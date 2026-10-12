from cooking_manager.packaging import Pack, candidate_sizes, estimated_grams, split_packaging


class TestCount:
    def test_x_suffix_leaves_the_name_clean(self):
        name, pack = split_packaging("Drive A Bio Plein Air Oeufs x12")
        assert name == "Drive A Bio Plein Air Oeufs"
        assert pack.count == 12

    def test_uppercase_x_too(self):
        assert split_packaging("Oeufs plein air X10")[1].count == 10

    def test_leading_count(self):
        name, pack = split_packaging("2 boîtes de thon listao")
        assert pack.count == 2
        assert name == "thon listao"


class TestSize:
    def test_weight_in_the_name(self):
        name, pack = split_packaging("Comté Juraflore AOP 250 g")
        assert name == "Comté Juraflore AOP"
        assert (pack.size_value, pack.size_unit) == (250.0, "g")

    def test_pack_of_size(self):
        name, pack = split_packaging("Poêlée méditerranéenne sachet 750 g")
        assert name == "Poêlée méditerranéenne"
        assert (pack.count, pack.size_value, pack.size_unit) == (1.0, 750.0, "g")

    def test_volume(self):
        assert split_packaging("Lait de coco 400 ml")[1].size_unit == "ml"


class TestLeaveAlone:
    def test_a_number_that_belongs_to_the_food(self):
        """« 5 baies » et « 4 fromages » nomment l'aliment, pas son emballage."""
        name, pack = split_packaging("Poivre 5 baies")
        assert name == "Poivre 5 baies"
        assert pack == Pack(None, None, None)

    def test_percentage_is_not_a_size(self):
        name, pack = split_packaging("Chocolat noir 70% cacao")
        assert name == "Chocolat noir 70% cacao"
        assert pack.size_value is None

    def test_plain_name_untouched(self):
        assert split_packaging("Comté") == ("Comté", Pack(None, None, None))


class TestCandidateSizes:
    def test_le_libelle_du_drive_sans_poids_emprunte_le_nom_de_l_application(self):
        sizes = candidate_sizes("Fromage blanc au lait demi-écrémé nature",
                                "Fromage blanc au lait demi-écrémé nature 1kg")
        assert sizes == [(1.0, "kg")]

    def test_un_nom_qui_porte_deux_conditionnements_les_rend_tous(self):
        assert candidate_sizes("Pâte à lasagnes 250g 6 pièces") == [(250.0, "g"), (6.0, "pièce")]

    def test_un_poids_au_milieu_du_nom_se_lit(self):
        sizes = candidate_sizes("Skyr nature 0% recette", "Skyr nature 0% recette 850g 8/9 parts")
        assert sizes == [(850.0, "g")]

    def test_des_cubes_se_comptent_comme_des_pieces(self):
        sizes = candidate_sizes("Bouillon en cube goût volaille", "Bouillon en cube 12x10g 12 cubes")
        assert sizes == [(12.0, "pièce")]

    def test_sans_aucun_poids_la_liste_est_vide(self):
        assert candidate_sizes("Tomates rondes en grappe", "environ 3-4 fruits") == []


class TestPourcentage:
    def test_un_pourcentage_dans_le_nom_ne_masque_pas_le_poids(self):
        name, pack = split_packaging("Be Nuts Purée de cacahuètes 100% 520g")
        assert (pack.size_value, pack.size_unit) == (520.0, "g")
        assert name == "Be Nuts Purée de cacahuètes 100%"

    def test_un_pourcentage_sans_poids_reste_sans_conditionnement(self):
        assert split_packaging("Chocolat noir 70% cacao")[1].size_value is None


class TestEstimatedGrams:
    def test_environ_trois_quatre_fruits_prend_le_poids_moyen_de_la_piece(self):
        assert estimated_grams("Tomates rondes en grappe france environ 3-4 fruits", "tomate") == 525.0

    def test_un_aliment_sans_poids_typique_ne_s_estime_pas(self):
        assert estimated_grams("Chose environ 3-4 fruits", "kiwi") is None

    def test_un_nom_sans_nombre_de_fruits_ne_s_estime_pas(self):
        assert estimated_grams("Tomates rondes en grappe", "tomate") is None


class TestUneBoiteDOeufsSeCompte:
    def test_douze_oeufs_font_douze_pieces(self):
        assert (12.0, "pièce") in candidate_sizes("Oeufs de poules élevées en plein air",
                                                  "Oeufs de poules élevées en plein air 12 œufs")

    def test_oeufs_sans_ligature(self):
        assert (6.0, "pièce") in candidate_sizes("Oeufs bio 6 oeufs")


class TestUnePieceSePeseQuandLeBesoinEstEnGrammes:
    def test_dix_courgettes_a_la_piece(self):
        from cooking_manager.packaging import grams_for_pieces

        assert grams_for_pieces("courgette", 10) == 2500.0

    def test_un_aliment_sans_poids_typique_reste_illisible(self):
        from cooking_manager.packaging import grams_for_pieces

        assert grams_for_pieces("dorade royale", 4) is None


class TestConvertEstimated:
    def test_pieces_en_grammes_et_retour(self):
        from cooking_manager.packaging import convert_estimated

        assert convert_estimated("courgette", 3, "pièces", "g") == 750.0
        assert convert_estimated("courgette", 1, "kg", "pièce") == 4.0
        assert convert_estimated("courgette", 500, "g", "kg") == 0.5

    def test_equivalent_de_la_table_dans_les_deux_sens(self):
        from cooking_manager.packaging import convert_estimated

        assert convert_estimated("ail", 3, "tête", "gousse") == 30.0
        assert convert_estimated("ail", 5, "gousses", "tête") == 0.5

    def test_rien_ne_s_applique_rend_none(self):
        from cooking_manager.packaging import convert_estimated

        assert convert_estimated("kiwi", 3, "pièce", "g") is None
        assert convert_estimated("courgette", 3, "pièce", "ml") is None

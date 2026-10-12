"""Un produit nommé au panier rejoint son aliment : sans `food_key`, verify le dit « hors appli »."""

import pytest

from cooking_manager.matching import resolve_food_key

MENU = [
    ("oeuf", "oeuf"),
    ("fromage blanc", "fromage-blanc"),
    ("filet de poulet", "poulet"),
    ("lait", "lait"),
    ("lait de coco", "lait-de-coco"),
    ("riz basmati", "riz-basmati"),
]


@pytest.mark.parametrize("demande,attendu", [
    ("oeufs plein air", "oeuf"),
    ("fromage blanc nature entier", "fromage-blanc"),
    ("riz basmati complet", "riz-basmati"),
    ("lait de coco", "lait-de-coco"),
])
def test_un_produit_nomme_rejoint_l_aliment_du_menu(demande, attendu):
    assert resolve_food_key(demande, MENU) == attendu


def test_un_complement_n_est_pas_le_meme_aliment():
    """« lait de coco » ne se rattache jamais à « lait »."""
    assert resolve_food_key("lait de coco", [("lait", "lait")]) is None


def test_deux_aliments_possibles_ne_se_devinent_pas():
    candidats = [("poivron rouge", "poivron-rouge"), ("poivron rouge", "poivron-doux")]
    assert resolve_food_key("poivron rouge", candidats) is None


def test_un_produit_sans_aliment_au_menu_reste_sans_cle():
    assert resolve_food_key("curcuma moulu", MENU) is None

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from cooking_manager.cart_freshness import (
    CartRow, gone_prefix, stale_lines, stale_payload, superseded_by, superseded_prefix)


def at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo("Europe/Paris"))


def row(id: int, food_key: str | None = "courgette", origin: str = "menu",
        status: str = "elected", created_at: datetime | None = None,
        requested: str = "courgette") -> CartRow:
    return CartRow(id, food_key, origin, status, created_at or at(5, 12, 28), requested)


def stale(rows, keys=("courgette",), rewritten=None, confirmed=None):
    return stale_lines(rows, menu_food_keys=set(keys), menu_rewritten_at=rewritten,
                       pantry_confirmed_at=confirmed)


class TestStaleLines:
    def test_courgette_du_05_10_est_perimee_par_la_reecriture(self):
        [found] = stale([row(1)], rewritten=at(5, 17, 30))
        assert (found.id, found.cause) == (1, "menu_rewritten")
        assert found.reason == (
            "élue le 05/10 12:28, avant la réécriture du menu (05/10 17:30) : à ré-élire")

    def test_aliment_retire_du_menu_meme_elu_apres_la_reecriture(self):
        late = row(1, created_at=at(5, 18, 0))
        [found] = stale([late], keys=("carotte",), rewritten=at(5, 17, 30))
        assert found.cause == "food_gone"
        assert found.reason == "courgette n'est plus au menu"

    def test_elue_apres_reecriture_et_confirmation_est_fraiche(self):
        late = row(1, created_at=at(5, 18, 0))
        assert stale([late], rewritten=at(5, 17, 30), confirmed=at(5, 17, 45)) == []

    def test_confirmation_du_garde_manger(self):
        [found] = stale([row(1)], rewritten=at(5, 8, 0), confirmed=at(5, 13, 5))
        assert found.cause == "pantry_confirmed"
        assert found.reason == (
            "élue le 05/10 12:28, avant la confirmation du garde-manger (05/10 13:05) : à ré-élire")

    def test_reecriture_prime_sur_confirmation(self):
        [found] = stale([row(1)], rewritten=at(5, 17, 30), confirmed=at(5, 18, 0))
        assert found.cause == "menu_rewritten"

    def test_confirmation_absente_ne_perime_rien(self):
        assert stale([row(1)], rewritten=None, confirmed=None) == []

    def test_ligne_manuelle_ancienne_jamais_perimee(self):
        old = row(1, origin="manual", food_key="pomme")
        assert stale([old], keys=(), rewritten=at(5, 17, 30), confirmed=at(5, 18, 0)) == []

    def test_ligne_pushed_ancienne_jamais_perimee(self):
        old = row(1, status="pushed")
        assert stale([old], keys=(), rewritten=at(5, 17, 30), confirmed=at(5, 18, 0)) == []

    def test_substitution_asked_est_jugee(self):
        sub = row(1, origin="substitution", status="asked")
        assert [s.id for s in stale([sub], rewritten=at(5, 17, 30))] == [1]

    def test_heure_affichee_a_paris_pour_une_entree_utc(self):
        utc = datetime(2026, 10, 5, 10, 28, tzinfo=timezone.utc)
        rewritten = datetime(2026, 10, 5, 15, 30, tzinfo=timezone.utc)
        [found] = stale([row(1, created_at=utc)], rewritten=rewritten)
        assert found.reason == (
            "élue le 05/10 12:28, avant la réécriture du menu (05/10 17:30) : à ré-élire")

    def test_elue_a_l_instant_de_la_reecriture_est_fraiche(self):
        assert stale([row(1, created_at=at(5, 17, 30))], rewritten=at(5, 17, 30),
                     confirmed=at(5, 17, 30)) == []

    def test_horodatage_naif_refuse(self):
        naive = datetime(2026, 10, 5, 12, 28)
        with pytest.raises(ValueError, match="fuseau"):
            stale([row(1, created_at=naive)], rewritten=at(5, 17, 30))
        with pytest.raises(ValueError, match="fuseau"):
            stale([row(1)], rewritten=naive)
        with pytest.raises(ValueError, match="fuseau"):
            stale([row(1)], confirmed=naive)

    def test_food_key_nul_ne_compte_pas_comme_retire(self):
        assert stale([row(1, food_key=None)], keys=()) == []

    def test_menu_sans_aliment_lie_ne_dit_pas_retire(self):
        assert stale([row(1)], keys=()) == []

    def test_menu_sans_aliment_lie_garde_les_autres_causes(self):
        [found] = stale([row(1)], keys=(), rewritten=at(5, 17, 30))
        assert found.cause == "menu_rewritten"


class TestSupersededBy:
    ROWS = [
        row(1), row(2, status="asked"), row(3, origin="substitution"),
        row(4, origin="manual"), row(5, food_key="carotte"), row(6, status="pushed"),
    ]

    def test_remplace_les_lignes_ouvertes_du_meme_aliment_et_du_meme_nom(self):
        assert superseded_by(self.ROWS, food_key="courgette", origin="menu",
                             requested="Courgettes") == [1, 2, 3]

    def test_food_key_nul_ou_origine_manuelle_ne_remplace_rien(self):
        assert superseded_by(self.ROWS, food_key=None, origin="menu", requested="courgette") == []
        assert superseded_by(self.ROWS, food_key="courgette", origin="manual",
                             requested="courgette") == []

    def test_deux_lignes_d_un_meme_food_key_aux_noms_differents_ne_se_remplacent_pas(self):
        rows = [row(1, food_key="ail", requested="ail"), row(2, food_key="ail", requested="ail poudre")]
        assert superseded_by(rows, food_key="ail", origin="menu", requested="ail poudre") == [2]
        assert superseded_by(rows, food_key="ail", origin="menu", requested="ail") == [1]


class TestPayloadEtMotifs:
    def test_payload_ajoute_le_food_key_de_la_ligne(self):
        rows = [row(1), row(2, food_key="tomate")]
        found = stale(rows, rewritten=at(5, 17, 30))
        payload = stale_payload(rows, found)
        assert [(p["id"], p["food_key"], p["cause"]) for p in payload] == [
            (1, "courgette", "menu_rewritten"), (2, "tomate", "food_gone")]
        assert all(p["reason"] for p in payload)

    def test_prefixes_de_motif(self):
        assert superseded_prefix(7) == "remplacée par la ligne 7 — "
        assert gone_prefix("courgette") == "périmée : courgette n'est plus au menu — "

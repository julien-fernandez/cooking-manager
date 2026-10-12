"""Chaque gate câblé distingue son connu-faux de son connu-vrai — sinon il ne mesure rien (spec 01 § 10)."""

import pytest

from cooking_manager import gates as g

COMPAT_OK = {"leftovers_unsourced": [], "conflicts_uncovered": 0, "parts_unmentioned": []}
SHOP_OK = {"slots_uncomposed": {"measured": True, "reason": "", "slots": []},
           "meals_unmatched": []}
CONFIRMED = {"ok": True, "blind": False, "reason": None, "note": None,
             "confirmed_at": "2026-10-07", "lines_count": 12}


def cart(*lines):
    return {"lines": [{"requested": r, "status": s, "stale": st} for r, s, st in lines]}


KNOWN = {
    "tablee_unresolved": ({"days": ["2026-10-06"], "unsynced": ["2026-10-06"]},
                          {"days": ["2026-10-06"], "unsynced": []}),
    "slots_uncomposed": ({**SHOP_OK, "slots_uncomposed": {"measured": True, "reason": "",
                          "slots": [{"date": "2026-10-08", "slot": "dinner"}]}}, SHOP_OK),
    "meals_orphan": ({**SHOP_OK, "meals_unmatched": [{"day": "jeudi", "slot": "dinner"}]},
                     SHOP_OK),
    "conflicts_uncovered": ({**COMPAT_OK, "conflicts_uncovered": 2}, COMPAT_OK),
    "parts_unmentioned": ({**COMPAT_OK, "parts_unmentioned": [{"recipe": "x", "part": "riz"}]},
                          COMPAT_OK),
    "pantry_blind": ({"ok": False, "blind": False,
                      "reason": "garde-manger non confirmé pour le menu 2026-w41", "note": None},
                     CONFIRMED),
    "food_pending": (["creme"], []),
    "cart_asked": (cart(("pain complet", "asked", None)), cart(("pain complet", "elected", None))),
    "cart_stale": (cart(("pain complet", "elected", {"cause": "menu", "reason": "menu réécrit"})),
                   cart(("pain complet", "elected", None))),
    "verify_missing": ({"last": {"state": g.KO, "value": 1.0, "detail": {"missing": ["persil-plat"]},
                                 "cart_fingerprint": "abc", "measured_at": "2026-10-07T10:00"},
                        "fingerprint": "abc"},
                       {"last": {"state": g.OK, "value": 0.0, "detail": {"missing": []},
                                 "cart_fingerprint": "abc", "measured_at": "2026-10-07T10:00"},
                        "fingerprint": "abc"}),
    "published": ({"status": "proposed", "active_menus": 1},
                  {"status": "active", "active_menus": 1}),
}


def test_chaque_gate_cable_a_ses_deux_cas_et_ils_different():
    wired = {gate.id for gate in g.GATES if gate.wired}
    assert wired == set(KNOWN), "un gate câblé sans connu-faux/connu-vrai ne se câble pas"
    for gate_id, (bad, good) in KNOWN.items():
        gate = g.GATES_BY_ID[gate_id]
        assert g.run(gate, bad).state != g.run(gate, good).state, gate_id
        assert g.run(gate, good).state == g.OK, gate_id


def test_registre_ordonne_et_specs_portees():
    assert [gate.step for gate in g.GATES] == sorted(
        (gate.step for gate in g.GATES), key=g.STEP_ORDER.index)
    for gate in g.GATES:
        assert gate.step in g.STEPS
        assert gate.wired or gate.spec, f"{gate.id} pas câblé sans sa spec"
    assert len({gate.id for gate in g.GATES}) == len(g.GATES)


def test_pas_cable_n_est_jamais_vert():
    result = g.run(g.GATES_BY_ID["window_undecided"], None)
    assert result.state == g.NOT_WIRED and result.spec == "04"


def test_confirmation_aveugle_reste_rouge():
    blind = {"ok": True, "blind": True, "reason": None,
             "note": "confirmé À L'AVEUGLE le 2026-10-07 — pas le temps : aucune ligne n'a été regardée"}
    result = g.run(g.GATES_BY_ID["pantry_blind"], blind)
    assert result.state == g.KO and "AVEUGLE" in result.detail["reason"]


def test_semaine_non_synchronisee_n_est_pas_mesuree():
    result = g.run(g.GATES_BY_ID["tablee_unresolved"],
                   {"days": ["2026-10-06"], "unsynced": ["2026-10-06"]})
    assert result.state == g.UNMEASURED and result.value == 1


def test_menu_sans_jour_date_n_est_pas_mesure():
    result = g.run(g.GATES_BY_ID["tablee_unresolved"], {"days": [], "unsynced": []})
    assert result.state == g.UNMEASURED


def test_reste_sans_source_rend_les_conflits_non_mesures():
    compat = {**COMPAT_OK, "leftovers_unsourced": [{"day": "mardi", "slot": "lunch"}]}
    assert g.run(g.GATES_BY_ID["conflicts_uncovered"], compat).state == g.UNMEASURED


def test_couverture_non_mesuree():
    shop = {**SHOP_OK, "slots_uncomposed": {"measured": False, "reason": "aucun repas daté",
                                            "slots": []}}
    assert g.run(g.GATES_BY_ID["slots_uncomposed"], shop).state == g.UNMEASURED


def test_champ_renomme_rend_non_mesure_jamais_vert():
    assert g.run(g.GATES_BY_ID["meals_orphan"], {"renamed": []}).state == g.UNMEASURED


def test_entree_illisible_rend_non_mesure():
    result = g.run(g.GATES_BY_ID["cart_asked"], g.LoadError("HTTPException: 404"))
    assert result.state == g.UNMEASURED and "404" in result.detail["reason"]


@pytest.mark.parametrize("last,fingerprint,state", [
    (None, "abc", g.UNMEASURED),
    ({"state": g.OK, "value": 0.0, "detail": {}, "cart_fingerprint": "old",
      "measured_at": "2026-10-07T10:00"}, "abc", g.UNMEASURED),
])
def test_verify_relu_sans_mesure_valable(last, fingerprint, state):
    gate = g.GATES_BY_ID["verify_missing"]
    assert g.run(gate, {"last": last, "fingerprint": fingerprint}).state == state


def test_verify_relu_porte_sa_date():
    gate = g.GATES_BY_ID["verify_missing"]
    result = g.run(gate, KNOWN["verify_missing"][1])
    assert result.as_of == "2026-10-07T10:00"


def test_verify_measure_le_persil():
    """Persil frisé au panier pour un besoin de persil plat rend MANQUE sur l'aliment."""
    payload = {"measured": True, "per_food": [
        {"food": "persil-plat", "verdict": "MANQUE"},
        {"food": "persil-frise", "verdict": "SURPLUS"}]}
    result = g.verify_measure(payload)
    assert result.state == g.KO and result.detail["missing"] == ["persil-plat"]


def test_verify_measure_panier_illisible():
    result = g.verify_measure({"measured": False, "reason": "illisible : session anonyme",
                               "per_food": [], "counts": {}})
    assert result.state == g.UNMEASURED


def test_empreinte_ignore_les_lignes_sautees_et_l_ordre():
    a = [{"id": 2, "status": "pushed", "quantity": 1}, {"id": 1, "status": "elected", "quantity": 2},
         {"id": 3, "status": "skipped", "quantity": 1}]
    b = [a[1], a[0]]
    assert g.cart_fingerprint(a) == g.cart_fingerprint(b)
    assert g.cart_fingerprint(a) != g.cart_fingerprint([{**a[1], "quantity": 3}, a[0]])


def results_with(**states):
    out = {gate.id: g.run(gate, None) if not gate.wired
           else g.GateResult(gate.id, g.OK, 0, gate.threshold) for gate in g.GATES}
    for gate_id, state in states.items():
        out[gate_id] = g.GateResult(gate_id, state, 1, 0, {"reason": "test"})
    return out


def test_regle_cumulative():
    ids = lambda t: [gate.id for gate in g.required_gates(t) if gate.wired]  # noqa: E731
    assert ids("publish") == ["tablee_unresolved", "slots_uncomposed", "meals_orphan",
                              "conflicts_uncovered", "parts_unmentioned"]
    assert ids("elect") == ids("publish") + ["pantry_blind"]
    assert ids("push") == ids("elect") + ["food_pending", "cart_asked", "cart_stale"]
    assert ids("order") == ids("push") + ["verify_missing"]


def test_pas_cable_ne_bloque_pas_mais_se_nomme():
    decision = g.decide("push", results_with())
    assert decision["allowed"] and "lines_unassigned" in decision["not_wired"]


def test_non_mesure_bloque():
    decision = g.decide("elect", results_with(tablee_unresolved=g.UNMEASURED))
    assert not decision["allowed"] and decision["blocking"] == ["tablee_unresolved"]


def test_gate_d_une_etape_posterieure_ne_bloque_pas():
    assert g.decide("elect", results_with(cart_asked=g.KO))["allowed"]


def test_statut_d_etape_pire_gate_et_force():
    ok = g.GateResult("a", g.OK)
    ko = g.GateResult("b", g.KO)
    unknown = g.GateResult("c", g.UNMEASURED)
    assert g.step_status([ok, ko, unknown], {}) == "rouge"
    assert g.step_status([ok, unknown], {}) == "non_mesuré"
    assert g.step_status([ok, ko], {"b": "accord de Julien"}) == "forcé"
    assert g.step_status([ok], {"a": "vieux forçage"}) == "vert"
    assert g.step_status([g.GateResult("d", g.NOT_WIRED)], {}) == "pas_câblé"


def test_rapport_position_et_transitions_coherentes():
    results = results_with(pantry_blind=g.KO)
    rep = g.report("2026-w41", results, {}, "2026-10-07T19:00:00+00:00")
    assert rep["position"] == {"last_green_step": "4", "next_transition": "elect"}
    assert rep["transitions"]["publish"] == {"allowed": True, "blocking": []}
    assert rep["transitions"]["elect"] == {"allowed": False, "blocking": ["pantry_blind"]}
    steps = {s["step"]: s for s in rep["steps"]}
    assert [s["step"] for s in rep["steps"]] == g.STEP_ORDER
    assert steps["5"]["status"] == "pas_câblé" and steps["6"]["status"] == "rouge"
    assert steps["6"]["gates"][0]["label"] == "Revue du garde-manger de ce menu"


def test_rapport_etape_forcee_porte_son_motif():
    rep = g.report("m", results_with(pantry_blind=g.KO), {"pantry_blind": "accord de Julien"}, "t")
    step6 = next(s for s in rep["steps"] if s["step"] == "6")
    assert step6["status"] == "forcé" and step6["forced_reason"] == "accord de Julien"
    assert rep["transitions"]["elect"]["allowed"] is False


def test_verify_measure_besoins_sans_aliment_non_confrontes():
    payload = {"measured": True, "per_food": [],
               "food_link": {"linked": 3, "unlinked": 2, "total": 5}}
    result = g.verify_measure(payload)
    assert result.state == g.UNMEASURED
    assert "2 besoin(s) sans aliment" in result.detail["reason"]


def test_verify_measure_tout_rattache_reste_vert():
    payload = {"measured": True, "per_food": [],
               "food_link": {"linked": 5, "unlinked": 0, "total": 5}}
    assert g.verify_measure(payload).state == g.OK


def test_forcages_ignorent_un_gate_alors_vert():
    rows = [{"gate_id": "a", "outcome": "forcé", "state": "mesuré_ko", "override_reason": "ok"},
            {"gate_id": "b", "outcome": "forcé", "state": "mesuré_ok", "override_reason": "vieux"},
            {"gate_id": "c", "outcome": "forcé", "state": "non_mesuré", "override_reason": "x"},
            {"gate_id": "d", "outcome": "refusé", "state": "mesuré_ko", "override_reason": None}]
    assert g.forced_reasons(rows) == {"a": "ok", "c": "x"}

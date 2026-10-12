"""Les gates de la semaine : un quantificateur recalculé depuis la base, quatre états (ADR 0044)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from cooking_manager.verification import MISSING

OK = "mesuré_ok"
KO = "mesuré_ko"
UNMEASURED = "non_mesuré"
NOT_WIRED = "pas_câblé"

STEPS: dict[str, str] = {
    "1": "Tablée", "2": "Repas composés", "3": "Fiches reliées", "4": "Compat & préférences",
    "5": "Fenêtre de calcul", "6": "Garde-manger confronté", "7a": "Aliment du besoin",
    "7b": "Canal", "7c": "Produit", "8": "Panier posé", "8.5": "Créneau réservé",
    "9": "Commande prouvée", "10": "Réception", "11": "Publié iPad",
}
STEP_ORDER = list(STEPS)


@dataclass(frozen=True)
class GateResult:
    id: str
    state: str
    value: float | None = None
    threshold: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    as_of: str | None = None
    spec: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "state": self.state, "value": self.value,
                               "threshold": self.threshold, "detail": self.detail}
        if self.as_of:
            out["as_of"] = self.as_of
        if self.spec:
            out["spec"] = self.spec
        return out


@dataclass(frozen=True)
class Gate:
    id: str
    step: str
    label: str
    measure: Callable[[Gate, Any], GateResult] | None = None
    threshold: int = 0
    spec: str | None = None

    @property
    def wired(self) -> bool:
        return self.measure is not None


@dataclass(frozen=True)
class LoadError:
    """Une entrée qu'aucun loader n'a pu lire : son gate n'est pas mesuré, jamais vert."""
    message: str


def _count(gate: Gate, n: int, detail: dict[str, Any]) -> GateResult:
    return GateResult(gate.id, OK if n <= gate.threshold else KO, n, gate.threshold, detail)


def _unmeasured(gate: Gate, reason: str, value: float | None = None,
                **extra: Any) -> GateResult:
    return GateResult(gate.id, UNMEASURED, value, gate.threshold, {"reason": reason, **extra})


def _tablee(gate: Gate, inputs: dict) -> GateResult:
    days, unsynced = inputs["days"], inputs["unsynced"]
    if not days:
        return _unmeasured(gate, "aucun repas daté à venir : la tablée ne se confronte à rien")
    if unsynced:
        return _unmeasured(gate, "semaine enfants non synchronisée : POST /api/child-week/sync?day=",
                           value=len(unsynced), days=unsynced)
    return _count(gate, 0, {"days": len(days)})


def _slots(gate: Gate, shopping: dict) -> GateResult:
    coverage = shopping["slots_uncomposed"]
    if not coverage["measured"]:
        return _unmeasured(gate, coverage["reason"])
    return _count(gate, len(coverage["slots"]), {"slots": coverage["slots"]})


def _orphans(gate: Gate, shopping: dict) -> GateResult:
    unmatched = shopping["meals_unmatched"]
    return _count(gate, len(unmatched), {"meals": unmatched})


def _conflicts(gate: Gate, compat: dict) -> GateResult:
    if compat["leftovers_unsourced"]:
        return _unmeasured(gate, "reste sans source : ses ingrédients ne sont pas contrôlés",
                           leftovers=compat["leftovers_unsourced"])
    return _count(gate, compat["conflicts_uncovered"], {})


def _parts(gate: Gate, compat: dict) -> GateResult:
    parts = compat["parts_unmentioned"]
    return _count(gate, len(parts), {"parts": parts})


def _pantry(gate: Gate, confirmation: dict) -> GateResult:
    if not confirmation["ok"]:
        return _count(gate, 1, {"reason": confirmation["reason"]})
    if confirmation["blind"]:
        return _count(gate, 1, {"reason": confirmation["note"]})
    return _count(gate, 0, {"confirmed_at": confirmation.get("confirmed_at"),
                            "lines_count": confirmation.get("lines_count")})


def _pending(gate: Gate, pending: list[str]) -> GateResult:
    return _count(gate, len(pending), {"names": sorted(pending)})


def _asked(gate: Gate, cart: dict) -> GateResult:
    asked = [line["requested"] for line in cart["lines"] if line["status"] == "asked"]
    return _count(gate, len(asked), {"requested": asked})


def _stale(gate: Gate, cart: dict) -> GateResult:
    stale = [{"requested": line["requested"], **line["stale"]}
             for line in cart["lines"] if line["stale"]]
    return _count(gate, len(stale), {"lines": stale})


def _verify_reread(gate: Gate, inputs: dict) -> GateResult:
    last, current = inputs["last"], inputs["fingerprint"]
    if last is None:
        return _unmeasured(gate, "aucun verify pour ce menu")
    if last["cart_fingerprint"] != current:
        return _unmeasured(gate, f"panier modifié depuis le verify du {last['measured_at']}")
    return GateResult(gate.id, last["state"], last["value"], gate.threshold, last["detail"],
                      as_of=last["measured_at"])


def _published(gate: Gate, inputs: dict) -> GateResult:
    live = inputs["status"] == "active" and inputs["active_menus"] == 1
    return GateResult(gate.id, OK if live else KO, 1 if live else 0, gate.threshold,
                      {"status": inputs["status"], "active_menus": inputs["active_menus"]})


GATES: tuple[Gate, ...] = (
    Gate("tablee_unresolved", "1", "Jours sans tablée résolue", _tablee),
    Gate("slots_uncomposed", "2", "Créneaux à table sans plat", _slots),
    Gate("meals_orphan", "3", "Repas sans fiche reliée", _orphans),
    Gate("conflicts_uncovered", "4", "Conflits non couverts", _conflicts),
    Gate("parts_unmentioned", "4", "Parts qu'aucune étape ne nomme", _parts),
    Gate("window_undecided", "5", "Repas passés non tranchés", spec="04"),
    Gate("pantry_blind", "6", "Revue du garde-manger de ce menu", _pantry),
    Gate("food_pending", "7a", "Besoins sans aliment tranché", _pending),
    Gate("lines_unassigned", "7b", "Lignes sans canal", spec="02"),
    Gate("drive_needs_without_product", "7c", "Besoins drive sans produit ni question",
         spec="03"),
    Gate("cart_asked", "8", "Lignes du panier en question", _asked),
    Gate("cart_stale", "8", "Lignes du panier périmées", _stale),
    Gate("slot_reserved", "8.5", "Créneau réservé avant l'heure limite", spec="02"),
    Gate("verify_missing", "9", "Besoins en MANQUE au dernier verify", _verify_reread),
    Gate("receipt_gap", "10", "Écart commandé − livré", spec="03"),
    Gate("published", "11", "Menu publié sur l'iPad", _published, threshold=1),
)
GATES_BY_ID = {gate.id: gate for gate in GATES}


def run(gate: Gate, inputs: Any) -> GateResult:
    """Un gate qui lève, ou dont l'entrée manque, rend `non_mesuré` — jamais vert."""
    if gate.measure is None:
        return GateResult(gate.id, NOT_WIRED, threshold=gate.threshold, spec=gate.spec)
    if isinstance(inputs, LoadError):
        return _unmeasured(gate, f"lecture impossible : {inputs.message}")
    try:
        return gate.measure(gate, inputs)
    except Exception as exc:  # noqa: BLE001 — l'exception devient le motif du non-mesuré
        return _unmeasured(gate, f"{type(exc).__name__}: {exc}")


def verify_measure(payload: dict) -> GateResult:
    """Le verdict d'un `verify` au moment où il a lu le panier — à journaliser avec l'empreinte."""
    gate = GATES_BY_ID["verify_missing"]
    if not payload.get("measured"):
        return _unmeasured(gate, payload.get("reason") or "panier non lu")
    unlinked = payload.get("food_link", {}).get("unlinked", 0)
    if unlinked > 0:
        return _unmeasured(gate, f"{unlinked} besoin(s) sans aliment : non confrontés au panier",
                           value=unlinked)
    missing = [entry["food"] for entry in payload["per_food"] if entry["verdict"] == MISSING]
    return _count(gate, len(missing), {"missing": missing})


def forced_reasons(latest: Iterable[dict]) -> dict[str, str]:
    """Un forçage ne s'attribue qu'à un gate alors rouge ou non mesuré, jamais à un gate déjà vert."""
    return {r["gate_id"]: r["override_reason"] for r in latest
            if r["outcome"] == "forcé" and r["state"] in (KO, UNMEASURED)}


def cart_fingerprint(rows: Iterable[dict]) -> str:
    """Les lignes vivantes du panier, hachées : un verify ne vaut que pour le panier qu'il a lu."""
    live = sorted((r["id"], r["status"], r["quantity"]) for r in rows if r["status"] != "skipped")
    return hashlib.sha256(json.dumps(live).encode()).hexdigest()[:16]


TRANSITIONS = ("publish", "elect", "push", "order")
PUBLISH_STEPS = ("1", "2", "3", "4")
TRANSITION_BEFORE = {"elect": "7a", "push": "8.5", "order": "10"}


def required_gates(transition: str) -> list[Gate]:
    """Une transition exige toutes les étapes strictement avant celle-ci ; la carte se déduit du registre."""
    if transition == "publish":
        steps = set(PUBLISH_STEPS)
    else:
        steps = set(STEP_ORDER[:STEP_ORDER.index(TRANSITION_BEFORE[transition])])
    return [gate for gate in GATES if gate.step in steps]


def decide(transition: str, results: dict[str, GateResult]) -> dict[str, Any]:
    """Un gate exigé `mesuré_ko` ou `non_mesuré` bloque ; un `pas_câblé` se nomme sans bloquer."""
    required = required_gates(transition)
    red = [results[gate.id] for gate in required
           if gate.wired and results[gate.id].state in (KO, UNMEASURED)]
    return {"allowed": not red, "blocking": [r.id for r in red], "red": red,
            "not_wired": [gate.id for gate in required if not gate.wired]}


def step_status(results: list[GateResult], forced: dict[str, str]) -> str:
    """Le pire gate fait l'étape : rouge > non mesuré > forcé > vert."""
    live = [r for r in results if r.state != NOT_WIRED]
    if not live:
        return NOT_WIRED
    if any(r.state == KO and r.id not in forced for r in live):
        return "rouge"
    if any(r.state == UNMEASURED and r.id not in forced for r in live):
        return UNMEASURED
    if any(r.state in (KO, UNMEASURED) for r in live):
        return "forcé"
    return "vert"


def report(slug: str, results: dict[str, GateResult], forced: dict[str, str],
           computed_at: str, window: dict[str, Any] | None = None) -> dict[str, Any]:
    """Le corps de `GET /gates` — `transitions` vient de `decide`, comme le 409."""
    steps = []
    for step in STEP_ORDER:
        gates = [gate for gate in GATES if gate.step == step]
        step_results = [results[gate.id] for gate in gates]
        status = step_status(step_results, forced)
        entry: dict[str, Any] = {
            "step": step, "label": STEPS[step], "status": status,
            "gates": [{"label": gate.label, **results[gate.id].as_dict()} for gate in gates]}
        if status == "forcé":
            entry["forced_reason"] = next(forced[r.id] for r in step_results if r.id in forced
                                          and r.state in (KO, UNMEASURED))
        steps.append(entry)

    last_green = None
    for entry in steps:
        if entry["status"] == NOT_WIRED:
            continue
        if entry["status"] != "vert":
            break
        last_green = entry["step"]

    transitions = {}
    for transition in TRANSITIONS:
        decision = decide(transition, results)
        transitions[transition] = {"allowed": decision["allowed"],
                                   "blocking": decision["blocking"]}
    blocked = next((t for t in TRANSITIONS[1:] if not transitions[t]["allowed"]), None)
    body: dict[str, Any] = {
        "slug": slug, "computed_at": computed_at,
        "position": {"last_green_step": last_green, "next_transition": blocked},
        "steps": steps, "transitions": transitions}
    if window:
        body["window"] = window
    return body

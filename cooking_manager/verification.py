"""Confronter le panier RÉEL du drive à la liste arrêtée — jamais l'appli à elle-même (#157)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from .ingredients import normalize_name
from .packaging import convert_estimated, grams_for_pieces
from .pantry import ENOUGH as OUTCOME_ENOUGH, MISSING as OUTCOME_MISSING, PARTIAL as OUTCOME_PARTIAL, STAPLE as OUTCOME_STAPLE, UNKNOWN as OUTCOME_UNKNOWN

MISSING = "MANQUE"
OK = "ok"
SURPLUS = "SURPLUS"
OFF_MENU_ASSUMED = "hors_menu_assume"
OFF_APP = "hors_appli"
UNMEASURABLE = "non_mesurable"
STOCK_INCOMPARABLE = "stock_incomparable"
DECIDED_BY_HAND = "decide_a_la_main"
OFF_DRIVE = "hors_drive"

BLOCKING = (MISSING, OFF_APP, UNMEASURABLE)

MANUAL = "manual"
RECURRENT = "recurrent"
ASSUMED_ORIGINS = (MANUAL, RECURRENT)

MEASURES = ("g", "ml")
PIECE_UNITS = ("pièce", "piece")
SURPLUS_RATIO_UNKNOWN_PACK = 0.25

UNREADABLE = "panier Drive A illisible"


@dataclass(frozen=True)
class Need:
    """Ce que la liste arrêtée réclame pour un aliment, dans son unité de base."""

    food: str
    qty: float | None
    unit: str | None
    pack_size: float | None = None
    stock_unknown: bool = False
    off_drive: bool = False
    estimated: bool = False


@dataclass(frozen=True)
class CartLine:
    """Une ligne LUE chez le drive. `food` à None = aucune ligne de l'appli ne la porte."""

    label: str
    food: str | None = None
    qty: float | None = None
    unit: str | None = None
    origin: str = ""


@dataclass
class Judgement:
    verdict: str
    need: float | None
    cart: float | None
    unit: str | None
    reason: str = ""
    surplus_measurable: bool = True
    labels: list[str] = field(default_factory=list)


def lines_to_buy(shopping_lines: Iterable[Mapping]) -> list[Mapping]:
    """Les lignes dont la liste réclame un achat : ce que le stock couvre n'est pas au panier."""
    return [line for line in shopping_lines
            if line.get("purchase")
            and (line.get("outcome") in (OUTCOME_MISSING, OUTCOME_PARTIAL)
                 or line.get("assumed_empty"))]


def index_cart_rows(rows: Iterable[Mapping]) -> dict[str, Mapping]:
    """Les lignes de l'application par référence. Une ligne `skipped` ne prétend à aucun produit :
    elle partage celui d'une ligne vivante et, lue en dernier, la masquerait (fromage blanc #9/#10/#45)."""
    by_ref: dict[str, Mapping] = {}
    for row in sorted(rows, key=lambda r: r["id"]):
        if row.get("status") == "skipped":
            continue
        for ref in {str(row.get("offer_id") or ""), str(row.get("product_id") or ""),
                    str(row.get("drive_a_id") or "")} - {""}:
            by_ref[ref] = row
    return by_ref


def lines_stock_unknown(shopping_lines: Iterable[Mapping]) -> list[Mapping]:
    """Les lignes dont le stock est présent mais incomparable : un besoin réel, une quantité en stock inconnue."""
    return [line for line in shopping_lines
            if line.get("purchase") and line.get("outcome") == OUTCOME_UNKNOWN
            and not line.get("assumed_empty")]


def stock_question(line: Mapping) -> str | None:
    """La question d'une ligne au stock incomparable : on ne l'achète pas dans le doute, on la pose."""
    if not lines_stock_unknown([line]):
        return None
    pantry = line.get("pantry") or {}
    stock = pantry.get("qty_text") or pantry.get("status") or "du stock"
    unit = line.get("unit") or ""
    need = f"{line['qty']:g} {unit}".strip() if line.get("qty") is not None else "une quantité non chiffrée"
    return (f"Le garde-manger a {stock} de {line.get('name', '')} ; le menu en demande {need} : "
            "tu en as assez ? (réponds au garde-manger avec une quantité)")


def _lines_for(shopping_lines: Iterable[Mapping], food_key: str | None, requested: str,
               keys: Mapping[str, str]) -> list[Mapping]:
    """Les lignes de la liste qui portent cet aliment (par `food_key`, sinon par nom)."""
    wanted = normalize_name(requested)
    lines = list(shopping_lines)
    by_key = [ln for ln in lines if food_key and keys.get(ln.get("name_normalized", "")) == food_key]
    return by_key or [ln for ln in lines if ln.get("name_normalized") == wanted]


def stock_question_for(shopping_lines: Iterable[Mapping], *, food_key: str | None,
                       requested: str, keys: Mapping[str, str]) -> str | None:
    """La question de la ligne du menu qui porte cet aliment (par `food_key`, sinon par nom)."""
    candidates = _lines_for(shopping_lines, food_key, requested, keys)
    return next((q for ln in candidates if (q := stock_question(ln))), None)


def covered_by_stock_for(shopping_lines: Iterable[Mapping], *, food_key: str | None,
                         requested: str, keys: Mapping[str, str]) -> bool:
    """Vrai si la liste porte cet aliment et que le stock suffit sur chacune de ses lignes (`suffisant` ou `placard`, non supposé épuisé)."""
    candidates = _lines_for(shopping_lines, food_key, requested, keys)
    return bool(candidates) and all(
        ln.get("outcome") in (OUTCOME_ENOUGH, OUTCOME_STAPLE) and not ln.get("assumed_empty")
        for ln in candidates)


def unreadable(reason: str) -> dict:
    """Une lecture qui n'a pas eu lieu — jamais `ok`, jamais un panier réputé conforme."""
    return {"source": "drive_a", "ok": False, "measured": False,
            "reason": f"{UNREADABLE} : {reason}", "counts": {}, "per_food": []}


def _sum_lines(lines: list[CartLine]) -> tuple[float | None, str | None, list[str], str]:
    """Le total d'un aliment chez le drive — None dès qu'une ligne n'est pas mesurable ; 4e valeur : note d'estimation."""
    labels = [ln.label for ln in lines]
    for line in lines:
        if line.qty is None or not line.unit:
            return None, line.unit, labels, ""
    total, unit = 0.0, None
    for line in lines:
        if unit is not None and line.unit != unit:
            return _sum_in_grams(lines, labels)
        unit = line.unit
        total += line.qty or 0.0
    return total, unit, labels, ""


def _sum_in_grams(lines: list[CartLine], labels: list[str]) -> tuple[float | None, str | None, list[str], str]:
    """Des lignes en unités mêlées ramenées en g sur le poids typique — non mesurable si l'une n'a pas d'équivalent."""
    grams = [convert_estimated(ln.food, ln.qty or 0.0, ln.unit or "", "g") for ln in lines]
    if any(g is None for g in grams):
        return None, None, labels, ""
    converted = [ln for ln in lines if ln.unit not in ("g", "kg")]
    if not converted:
        return sum(g for g in grams if g is not None), "g", labels, ""
    pieces = sum(ln.qty or 0.0 for ln in converted)
    note = f"poids estimé du panier : {_pretty(pieces)} {converted[0].unit} au poids typique"
    return sum(g for g in grams if g is not None), "g", labels, note


def _judge(need: Need | None, lines: list[CartLine]) -> Judgement:
    """Le verdict d'un aliment ; toute estimation (panier ou besoin converti en g) s'écrit dans `reason`."""
    cart_note = _sum_lines(lines)[3]
    judged = _judge_summed(need, lines)
    notes = [n for n in (cart_note, "poids estimé du besoin" if need and need.estimated else "") if n]
    if notes:
        judged.reason = " ; ".join(filter(None, [judged.reason, *(n for n in notes if n not in judged.reason)]))
    return judged


def _judge_summed(need: Need | None, lines: list[CartLine]) -> Judgement:
    cart, cart_unit, labels, _ = _sum_lines(lines)

    if need is None:
        assumed = bool(lines) and all(line.origin in ASSUMED_ORIGINS for line in lines)
        off_app = any(line.food is None for line in lines)
        if assumed and any(line.origin == RECURRENT for line in lines):
            return Judgement(OFF_MENU_ASSUMED, 0.0, cart, cart_unit, labels=labels,
                             reason="achat d'habitude déclaré (récurrent), hors menu assumé")
        if off_app:
            return Judgement(OFF_APP, 0.0, cart, cart_unit, labels=labels,
                             reason="présent chez Drive A, absent de toute ligne de "
                                    "l'application — saisi hors de l'appli")
        if assumed:
            return Judgement(OFF_MENU_ASSUMED, 0.0, cart, cart_unit, labels=labels,
                             reason="ligne posée à la main, hors menu assumé")
        return Judgement(OFF_APP, 0.0, cart, cart_unit, labels=labels,
                         reason="aucun repas ne réclame cet aliment et aucune ligne "
                                "ne l'assume")

    if need.off_drive:
        return Judgement(OFF_DRIVE, need.qty, cart, need.unit, labels=labels,
                         reason="s'achète hors drive (préférence `off_drive`) : rien à "
                                "confronter au panier")
    if need.stock_unknown:
        return Judgement(STOCK_INCOMPARABLE, need.qty, cart, need.unit, labels=labels,
                         reason="le menu en a besoin, le stock est présent mais sa quantité est "
                                "incomparable : ce qui est au panier est un achat dans le doute")
    if not lines:
        cart, cart_unit = 0.0, need.unit
    if lines and (need.qty is None or not need.unit):
        return Judgement(DECIDED_BY_HAND, need.qty, cart, need.unit, labels=labels,
                         reason="la liste ne chiffre pas ce besoin (une dose, une quantité à "
                                "décider à la main) : un produit a été choisi, rien à confronter")
    if need.qty is None or not need.unit:
        return Judgement(UNMEASURABLE, need.qty, cart, need.unit, labels=labels,
                         reason="la liste ne chiffre pas ce besoin : rien à confronter")
    if cart is None:
        return Judgement(UNMEASURABLE, need.qty, None, need.unit, labels=labels,
                         reason="quantité illisible chez le drive : le contenant d'au "
                                "moins une ligne est inconnu")
    if need.unit in PIECE_UNITS and cart_unit == "g":
        grams = grams_for_pieces(need.food, need.qty)
        if grams is not None:
            return _judge_estimated(need, grams, lines)
    if cart_unit != need.unit:
        both_measures = need.unit in MEASURES and cart_unit in MEASURES
        return Judgement(UNMEASURABLE if both_measures else DECIDED_BY_HAND, need.qty, cart,
                         need.unit, labels=labels,
                         reason=f"unités incomparables : besoin en {need.unit}, panier en "
                                f"{cart_unit}"
                                + ("" if both_measures else
                                   " — un produit a été choisi, aucune équivalence connue"))

    if cart < need.qty:
        return Judgement(MISSING, need.qty, cart, need.unit, labels=labels,
                         reason="un repas de la semaine n'a pas son ingrédient")

    over = cart - need.qty
    if (need.pack_size is None and need.unit in MEASURES and need.qty > 0
            and over > SURPLUS_RATIO_UNKNOWN_PACK * need.qty):
        return Judgement(SURPLUS, need.qty, cart, need.unit, labels=labels, surplus_measurable=True,
                         reason=f"{_pretty(over)} {need.unit} de trop sur {_pretty(need.qty)} "
                                f"{need.unit} (+{_pretty(round(over / need.qty * 100, 1))} %), "
                                "contenant inconnu : jugé sur le poids")
    if need.pack_size is None:
        return Judgement(OK, need.qty, cart, need.unit, labels=labels,
                         surplus_measurable=False,
                         reason="aucun contenant connu : le surplus ne se mesure pas")
    if over > need.pack_size:
        return Judgement(SURPLUS, need.qty, cart, need.unit, labels=labels,
                         reason=f"{_pretty(over)} {need.unit} de trop, au-delà d'un "
                                f"contenant de {_pretty(need.pack_size)} {need.unit}")
    return Judgement(OK, need.qty, cart, need.unit, labels=labels)


def _judge_estimated(need: Need, grams: float, lines: list[CartLine]) -> Judgement:
    """Des pièces jugées sur leur poids typique : le verdict le dit, l'estimation ne passe pas pour une lecture."""
    pack = None if need.pack_size is None else grams_for_pieces(need.food, need.pack_size)
    judged = _judge(replace(need, qty=grams, unit="g", pack_size=pack), lines)
    unit = "pièce" if need.qty == 1 else "pièces"
    note = f"poids estimé : {_pretty(need.qty or 0)} {unit} × {_pretty(grams / (need.qty or 1))} g"
    judged.reason = f"{judged.reason} ({note})" if judged.reason else note
    return judged


def verify(needs: list[Need], lines: list[CartLine], read_at: str) -> dict:
    """Le panier lu chez le drive, aliment par aliment. `measured` se lit AVANT `per_food`."""
    by_food: dict[str, list[CartLine]] = {}
    for line in lines:
        by_food.setdefault(line.food or f"?{line.label}", []).append(line)

    wanted: dict[str, Need] = {}
    for need in needs:
        if need.food:
            wanted[need.food] = _add(wanted[need.food], need) if need.food in wanted else need
    per_food: list[dict] = []
    for food in sorted(set(wanted) | set(by_food)):
        judgement = _judge(wanted.get(food), by_food.get(food, []))
        per_food.append({"food": food, "need": judgement.need, "cart": judgement.cart,
                         "unit": judgement.unit, "verdict": judgement.verdict,
                         "reason": judgement.reason, "labels": judgement.labels,
                         "surplus_measurable": judgement.surplus_measurable})

    counts: dict[str, int] = {}
    for entry in per_food:
        counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
    blocking = [e for e in per_food if e["verdict"] in BLOCKING]
    return {"source": "drive_a", "read_at": read_at, "measured": True,
            "ok": not blocking, "reason": "" if not blocking else
            f"{len(blocking)} aliment(s) bloquant(s) : "
            + ", ".join(f"{e['food']} ({e['verdict']})" for e in blocking),
            "counts": counts, "blocking": blocking, "per_food": per_food}


def _add(first: Need, second: Need) -> Need:
    """Deux noms du même aliment : leurs quantités s'additionnent (en g si l'un est en pièces et pesable), ou le besoin devient non chiffré."""
    flags = {"stock_unknown": first.stock_unknown and second.stock_unknown,
             "off_drive": first.off_drive and second.off_drive}
    if first.qty is None or second.qty is None:
        return replace(first, qty=None, **flags)
    if first.unit == second.unit:
        return replace(first, qty=first.qty + second.qty, **flags)
    parts = [convert_estimated(n.food, qty, n.unit, "g") if n.unit else None
             for n, qty in ((first, first.qty), (second, second.qty))]
    if "g" not in (first.unit, second.unit) or None in parts:
        return replace(first, qty=None, **flags)
    pack = None if first.pack_size is None or not first.unit else convert_estimated(
        first.food, first.pack_size, first.unit, "g")
    return replace(first, qty=sum(p for p in parts if p is not None), unit="g", pack_size=pack,
                   estimated=True, **flags)


def _pretty(value: float) -> str:
    return str(int(value)) if value == int(value) else str(round(value, 2))

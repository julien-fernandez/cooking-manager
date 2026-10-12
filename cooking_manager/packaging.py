"""Séparer ce qu'un aliment EST de la façon dont il est vendu."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ingredients import UNIT_ALIASES

_UNIT_WORDS = sorted(
    (v for variants in UNIT_ALIASES.values() for v in variants),
    key=len,
    reverse=True,
)
_UNIT_LOOKUP = {v.lower(): canonical
                for canonical, variants in UNIT_ALIASES.items()
                for v in variants}

_PACK_WORDS = ("sachet", "sachets", "boîte", "boîtes", "boite", "boites",
               "paquet", "paquets", "pot", "pots", "brique", "briques",
               "barquette", "barquettes", "bocal", "bocaux")

_COUNT_SUFFIX = re.compile(r"\s*[xX×]\s*(\d+)\s*$")
_LEADING_COUNT = re.compile(
    r"^\s*(\d+)\s+(" + "|".join(_PACK_WORDS) + r")\s+(?:de\s+|d')?",
    re.IGNORECASE,
)
_PACK_SIZE = re.compile(
    r"\s*(?:(" + "|".join(_PACK_WORDS) + r")\s+)?"
    r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(re.escape(u) for u in _UNIT_WORDS) + r")\s*$",
    re.IGNORECASE,
)
_SIZE_ANYWHERE = re.compile(
    r"(?<![\w.,/])(\d+(?:[.,]\d+)?)\s*(" + "|".join(re.escape(u) for u in _UNIT_WORDS) + r")(?![\w])",
    re.IGNORECASE,
)

_EGG_COUNT = re.compile(r"(?<![\w.,/])(\d+)\s*(?:œufs?|oeufs?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Pack:
    """Comment un aliment est vendu — jamais ce qu'il est."""

    count: float | None = None
    size_value: float | None = None
    size_unit: str | None = None


def split_packaging(name: str) -> tuple[str, Pack]:
    """Nom brut → (nom sans conditionnement, conditionnement lu)."""
    if not name:
        return name, Pack()

    count: float | None = None
    size_value: float | None = None
    size_unit: str | None = None

    rest = name.strip()

    m = _COUNT_SUFFIX.search(rest)
    if m:
        count = float(m.group(1))
        rest = rest[: m.start()].strip()

    m = _LEADING_COUNT.match(rest)
    if m:
        count = float(m.group(1))
        rest = rest[m.end():].strip()

    m = _PACK_SIZE.search(rest)
    if m and m.group(3).lower() in _UNIT_LOOKUP:
        size_value = float(m.group(2).replace(",", "."))
        size_unit = _UNIT_LOOKUP[m.group(3).lower()]
        if m.group(1):
            count = count or 1.0
        rest = rest[: m.start()].strip()

    return (rest or name.strip()), Pack(count, size_value, size_unit)


def candidate_sizes(label: str, known_name: str = "") -> list[tuple[float, str]]:
    """Tous les poids/volumes/comptes d'un libellé drive, puis du nom posé par l'application.

    Le panier relu perd parfois le poids (« Fromage blanc … nature »), et un nom en porte plusieurs
    (« 250g 6 pièces ») : l'appelant choisit celui qui se compare au besoin."""
    found: list[tuple[float, str]] = []
    for text in (label, known_name):
        sizes = [(float(m.group(1).replace(",", ".")), _UNIT_LOOKUP[m.group(2).lower()])
                 for m in _SIZE_ANYWHERE.finditer(text or "")]
        sizes += [(float(m.group(1)), "pièce") for m in _EGG_COUNT.finditer(text or "")]
        for size in sizes:
            if size not in found:
                found.append(size)
    return found


TYPICAL_PIECE_GRAMS: dict[str, float] = {
    "tomate": 150.0, "pomme": 150.0, "poivron": 200.0, "oignon": 150.0, "citron": 100.0,
    "courgette": 250.0, "aubergine": 300.0, "banane": 120.0, "carotte": 100.0,
    "pilon poulet": 125.0, "brocoli": 400.0,
}

TYPICAL_UNIT_EQUIVALENTS: dict[tuple[str, str], tuple[float, str]] = {
    ("ail", "tête"): (10.0, "gousse"),
}

_UNIT_SPELLINGS = dict(_UNIT_LOOKUP, piece="pièce", pieces="pièce")


def _canonical_unit(qty: float, unit: str) -> tuple[float, str]:
    """Une unité ramenée à son orthographe unique, le kg passé en g."""
    unit = unit.strip().lower()
    unit = _UNIT_SPELLINGS.get(unit, unit)
    return (qty * 1000.0, "g") if unit == "kg" else (qty, unit)


def convert_estimated(food: str | None, qty: float, unit: str, target_unit: str) -> float | None:
    """Une quantité dans une autre unité, sur un poids ou équivalent TYPIQUE (estimation) — None sinon."""
    qty, unit = _canonical_unit(qty, unit)
    divisor, target = _canonical_unit(1.0, target_unit)
    if unit == target:
        return qty / divisor
    each = TYPICAL_PIECE_GRAMS.get(food or "")
    if each is not None and (unit, target) == ("pièce", "g"):
        return qty * each / divisor
    if each is not None and (unit, target) == ("g", "pièce"):
        return qty / each / divisor
    for (name, big), (count, small) in TYPICAL_UNIT_EQUIVALENTS.items():
        if name != food:
            continue
        if (unit, target) == (big, small):
            return qty * count / divisor
        if (unit, target) == (small, big):
            return qty / count / divisor
    return None


def grams_for_pieces(food_key: str | None, pieces: float) -> float | None:
    """Des pièces pesées au poids typique de l'aliment — une ESTIMATION, None s'il n'en a pas."""
    each = TYPICAL_PIECE_GRAMS.get(food_key or "")
    return None if each is None else pieces * each


_FRUITS_COUNT = re.compile(r"(?:environ\s+)?(\d+)(?:\s*[-–]\s*(\d+))?\s+(?:fruits?|pièces?)\b",
                           re.IGNORECASE)


def estimated_grams(name: str, food_key: str | None) -> float | None:
    """Le poids d'un produit vendu « environ 3-4 fruits » : nombre moyen × poids typique de la pièce.

    Une ESTIMATION : l'appelant la signale, elle ne se confond jamais avec un poids lu."""
    each = TYPICAL_PIECE_GRAMS.get(food_key or "")
    m = _FRUITS_COUNT.search(name or "")
    if each is None or m is None:
        return None
    low, high = float(m.group(1)), float(m.group(2) or m.group(1))
    return (low + high) / 2 * each

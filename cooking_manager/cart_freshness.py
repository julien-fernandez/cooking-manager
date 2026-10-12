"""Une ligne élue avant la réécriture du menu ou la confirmation du garde-manger est périmée (#186, #187)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .ingredients import normalize_name

FOOD_GONE = "food_gone"
MENU_REWRITTEN = "menu_rewritten"
PANTRY_CONFIRMED = "pantry_confirmed"

JUDGED_ORIGINS = ("menu", "substitution")
JUDGED_STATUSES = ("elected", "asked")

PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True)
class CartRow:
    """Une ligne du panier : origin menu|manual|recurrent|substitution, status elected|asked|pushed|failed|skipped."""

    id: int
    food_key: str | None
    origin: str
    status: str
    created_at: datetime
    requested: str = ""


@dataclass(frozen=True)
class Stale:
    """Une ligne à ré-élire : cause food_gone|menu_rewritten|pantry_confirmed."""

    id: int
    cause: str
    reason: str


def _judged(row: CartRow) -> bool:
    """Seules les lignes du menu encore ouvertes se périment."""
    return row.origin in JUDGED_ORIGINS and row.status in JUDGED_STATUSES


def _stamp(moment: datetime) -> str:
    """L'heure de Julien (Paris), la base rendant du UTC."""
    return moment.astimezone(PARIS).strftime("%d/%m %H:%M")


def _require_aware(moment: datetime | None, name: str) -> None:
    """Refuse un horodatage naïf : il ne se compare pas à un TIMESTAMPTZ."""
    if moment is not None and moment.tzinfo is None:
        raise ValueError(f"{name} doit porter un fuseau horaire")


def stale_lines(
    rows: Iterable[CartRow],
    *,
    menu_food_keys: set[str],
    menu_rewritten_at: datetime | None,
    pantry_confirmed_at: datetime | None,
) -> list[Stale]:
    """Les lignes à ré-élire : aliment retiré du menu (sans aliment lié, inconnu), puis menu réécrit, puis garde-manger confirmé."""
    _require_aware(menu_rewritten_at, "menu_rewritten_at")
    _require_aware(pantry_confirmed_at, "pantry_confirmed_at")
    stale: list[Stale] = []
    for row in rows:
        if not _judged(row):
            continue
        _require_aware(row.created_at, f"created_at de la ligne {row.id}")
        if menu_food_keys and row.food_key is not None and row.food_key not in menu_food_keys:
            stale.append(Stale(row.id, FOOD_GONE, f"{row.food_key} n'est plus au menu"))
        elif menu_rewritten_at is not None and row.created_at < menu_rewritten_at:
            stale.append(Stale(row.id, MENU_REWRITTEN, (
                f"élue le {_stamp(row.created_at)}, avant la réécriture du menu "
                f"({_stamp(menu_rewritten_at)}) : à ré-élire")))
        elif pantry_confirmed_at is not None and row.created_at < pantry_confirmed_at:
            stale.append(Stale(row.id, PANTRY_CONFIRMED, (
                f"élue le {_stamp(row.created_at)}, avant la confirmation du garde-manger "
                f"({_stamp(pantry_confirmed_at)}) : à ré-élire")))
    return stale


def superseded_by(rows: Iterable[CartRow], *, food_key: str | None, origin: str,
                  requested: str) -> list[int]:
    """Les ids des lignes ouvertes du même aliment ET du même nom demandé, qu'une ré-élection remplace."""
    if food_key is None or origin not in JUDGED_ORIGINS:
        return []
    name = normalize_name(requested)
    return [row.id for row in rows
            if _judged(row) and row.food_key == food_key and normalize_name(row.requested) == name]


def stale_payload(rows: Iterable[CartRow], stale: Iterable[Stale]) -> list[dict]:
    """Les lignes périmées telles que la route les dit : id, aliment, cause, motif."""
    food_keys = {row.id: row.food_key for row in rows}
    return [{"id": s.id, "food_key": food_keys.get(s.id), "cause": s.cause, "reason": s.reason}
            for s in stale]


def superseded_prefix(new_id: int) -> str:
    """Le début du motif d'une ligne remplacée par une ré-élection."""
    return f"remplacée par la ligne {new_id} — "


def covered_prefix() -> str:
    """Le début du motif d'une ligne que le stock couvre désormais."""
    return "couvert par le stock — "


def gone_prefix(food_key: str) -> str:
    """Le début du motif d'une ligne dont l'aliment a quitté le menu."""
    return f"périmée : {food_key} n'est plus au menu — "

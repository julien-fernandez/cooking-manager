"""Vue par recette du menu : chaque ingrédient, son aliment, son stock, son panier."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping

from .ingredients import normalize_name
from .pantry import ENOUGH, MISSING as STOCK_MISSING, NON_PURCHASE, PARTIAL, STAPLE, UNKNOWN
from .verification import DECIDED_BY_HAND, MISSING, OFF_APP, STOCK_INCOMPARABLE, UNMEASURABLE

CART_PROBLEMS = (MISSING, OFF_APP, UNMEASURABLE)

# Le plus douteux d'abord : deux lignes de même nom (g et cs) ne se masquent jamais.
_DOUBT_ORDER = (UNKNOWN, STOCK_MISSING, PARTIAL, ENOUGH, STAPLE)


def _index_lines(
    lines: Iterable[Mapping],
) -> tuple[dict[str, list[Mapping]], dict[str, list[Mapping]]]:
    """Les lignes par nom, et par nom absorbé : un libellé fusionné garde le verdict de son hôte.

    `build_needs` sépare un même nom par famille d'unité : une liste, jamais une seule ligne.
    """
    by_name: dict[str, list[Mapping]] = {}
    by_merged: dict[str, list[Mapping]] = {}
    for line in lines:
        by_name.setdefault(line["name_normalized"], []).append(line)
        for name in line.get("merged_from") or []:
            by_merged.setdefault(normalize_name(name), []).append(line)
    return by_name, by_merged


def _doubtful_first(candidates: list[Mapping]) -> Mapping:
    def rank(line: Mapping) -> int:
        outcome = line.get("outcome")
        return _DOUBT_ORDER.index(outcome) if outcome in _DOUBT_ORDER else 0
    return min(candidates, key=rank)


def _link(food_key: str | None, name_normalized: str, refused: Collection[str]) -> str:
    if food_key:
        return "linked"
    if name_normalized in NON_PURCHASE:
        return "non_purchase"
    return "refused" if name_normalized in refused else "unlinked"


def _cart(verify_by_food: Mapping[str, Mapping] | None, food_key: str | None) -> dict | None:
    """`None` dit « rien à confronter » ; un panier illisible se dit en tête de réponse, pas ici."""
    entry = (verify_by_food or {}).get(food_key) if food_key else None
    if entry is None:
        return None
    return {"verdict": entry["verdict"], "reason": entry["reason"], "qty": entry["cart"],
            "unit": entry["unit"], "labels": list(entry["labels"])}


def _reasons(link: str, line: Mapping | None, cart: dict | None, name: str) -> list[str]:
    reasons = []
    if link == "unlinked":
        reasons.append("unlinked")
    if line is None and name not in NON_PURCHASE:
        reasons.append("no_line")
    if (line is not None and line.get("outcome") == UNKNOWN) or (
            cart and cart["verdict"] == STOCK_INCOMPARABLE):
        reasons.append("stock_unknown")
    if cart and cart["verdict"] == DECIDED_BY_HAND:
        reasons.append("decided_by_hand")
    if cart and cart["verdict"] in CART_PROBLEMS:
        reasons.append("cart_problem")
    return reasons


def _name_of(ing: Mapping) -> str:
    """`name_normalized` vaut '' par défaut en base : `build_needs` le recalcule, la carte aussi."""
    return ing.get("name_normalized") or normalize_name(ing.get("name", ""))


def _basic_state(line: Mapping | None) -> str | None:
    """L'état d'un basique du placard dans la page, ou None pour un ingrédient ordinaire (ADR 0043)."""
    if line is None or not line.get("pantry_staple"):
        return None
    if line.get("outcome") == STAPLE:
        return "au_placard" if line.get("declared", True) else "jamais_declare"
    if line.get("outcome") == STOCK_MISSING:
        return "fini"
    return None

def build_ingredient_map(
    recipes: Iterable[Mapping],
    lines: Iterable[Mapping],
    verify_by_food: Mapping[str, Mapping] | None,
    refused: Collection[str],
) -> dict:
    """Redistribue les verdicts de la liste fusionnée sur les recettes qui les demandent.

    Rien n'est recalculé : le stock vient de la ligne de courses, le panier de `verify`.
    """
    recipes = list(recipes)
    by_name, by_merged = _index_lines(lines)
    # verify juge l'aliment de la ligne hôte (`_needs_by_food`) : on lit le panier par ce nom-là.
    food_of_name: dict[str, str] = {}
    for recipe in recipes:
        for ing in recipe["ingredients"]:
            if ing.get("food_key"):
                food_of_name.setdefault(_name_of(ing), ing["food_key"])

    counts = {"rows": 0, "foods": 0, "unlinked": 0, "no_line": 0, "stock_unknown": 0,
              "decided_by_hand": 0, "cart_problem": 0}
    foods: set[str] = set()
    out_recipes: list[dict] = []
    seen: set[str] = set()

    for recipe in recipes:
        if recipe["recipe_slug"] in seen:
            continue
        seen.add(recipe["recipe_slug"])
        items, basics = [], []
        for ing in recipe["ingredients"]:
            name = _name_of(ing)
            candidates = by_name.get(name) or by_merged.get(name) or []
            line = _doubtful_first(candidates) if candidates else None
            state = _basic_state(line)
            link = _link(ing.get("food_key"), name, refused)
            cart_food = (food_of_name.get(line["name_normalized"]) if line else None) \
                or ing.get("food_key")
            cart = _cart(verify_by_food, cart_food)
            reasons = _reasons(link, line, cart, name)
            if reasons:
                counts["rows"] += 1
                foods.add(name)
                for reason in reasons:
                    counts[reason] += 1
            titles = [t for c in candidates for t in c["recipes"]]
            entry = {
                "name": ing["name"], "name_normalized": name, "raw": ing.get("raw"),
                "food_key": ing.get("food_key"), "link": link,
                "menu_qty": line["qty"] if line else None,
                "menu_unit": line["unit"] if line else None,
                "stock": ({"outcome": line["outcome"], "reason": line["reason"],
                           "pantry": line["pantry"]} if line else None),
                "cart": cart,
                "shared_with": list(dict.fromkeys(t for t in titles if t != recipe["title"])),
                "review": bool(reasons), "reasons": reasons,
            }
            if state is None:
                items.append(entry)
            else:
                basics.append({**entry, "state": state})
        out_recipes.append({
            "recipe_slug": recipe["recipe_slug"], "title": recipe["title"],
            "day": recipe["day"], "slot": recipe["slot"], "photo_url": recipe["photo_url"],
            "ingredients": items,
            "pantry_basics": basics,
        })

    counts["foods"] = len(foods)
    return {"to_review": counts, "recipes": out_recipes}

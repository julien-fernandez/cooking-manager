"""Quantité en français (#204), dont `formatQuantity` de `web/app.js` est le miroir : changer l'un change l'autre."""

import math

from .purchase import COUNTABLE_UNITS

HALF_UNITS = frozenset({"gousse", "brin"})
QUARTER_UNITS = frozenset({"c.c.", "c.s.", "pincée", "scoop", "cuillère à café", "cuillère à soupe"})
INVARIABLE_UNITS = frozenset({"g", "kg", "mg", "ml", "cl", "dl", "l", "q.s."})
FRACTIONS = {0.25: "¼", 0.5: "½", 0.75: "¾"}
THIRDS = {0.33: "⅓", 0.67: "⅔"}


def _step(unit: str | None, scaled: bool) -> float | None:
    """Le pas d'arrondi d'une unité mise à l'échelle : une boîte ou un œuf entiers, une demi-gousse, un quart de cuillère."""
    if unit in COUNTABLE_UNITS:
        return 1.0 if scaled else None
    if unit in HALF_UNITS:
        return 0.5 if scaled else None
    if unit in QUARTER_UNITS:
        return 0.25 if scaled else None
    return None


def _round(n: float, digits: int = 0) -> float:
    """Arrondi au plus proche, demi vers le haut comme `Math.round` (le `round` de Python arrondit au pair)."""
    scale = 10 ** digits
    return math.floor(n * scale + 0.5) / scale


def _decimal(n: float) -> str:
    if n == 0:
        return "0"
    if n >= 100:
        text = f"{_round(n):g}"
    elif n >= 10:
        text = f"{_round(n, 1):g}"
    elif n >= 1:
        text = f"{_round(n, 2):g}"
    else:
        r = _round(n, 2)
        third = next((g for t, g in THIRDS.items() if abs(r - t) < 0.04), None)
        if third:
            return third
        text = f"{r:g}"
    return text.replace(".", ",")


def _number(n: float, measured: bool) -> str:
    """Une mesure (g, kg, ml…) garde sa virgule ; une pièce, une gousse, une cuillère prennent ½ ¼ ¾."""
    whole, frac = divmod(n, 1)
    glyph = None if measured else FRACTIONS.get(round(frac, 2))
    if glyph and abs(frac - round(frac, 2)) < 1e-9:
        return f"{int(whole)} {glyph}" if whole else glyph
    return _decimal(n)


def _plural(unit: str) -> str:
    if "." in unit or unit in INVARIABLE_UNITS:
        return unit
    head, _, rest = unit.partition(" ")
    if head.endswith(("s", "x", "z")):
        plural = head
    elif head.endswith("al"):
        plural = head[:-2] + "aux"
    else:
        plural = head + "s"
    return f"{plural} {rest}" if rest else plural


def format_quantity(qty_min: float | None, qty_max: float | None, unit: str | None,
                    mult: float = 1) -> str:
    """« ≈ » avoue un arrondi au pas de l'unité : un citron reste « ≈ 1 pièce » à 3 comme à 5 portions."""
    if qty_min is None:
        return ""
    step = _step(unit, mult != 1)
    bounds = [qty_min] if qty_max is None or qty_max == qty_min else [qty_min, qty_max]
    exact = [float(q) * mult for q in bounds]
    shown = [max(math.floor(v / step + 0.5) * step, step) if step else v for v in exact]
    approx = any(abs(s - v) > 0.01 for s, v in zip(shown, exact, strict=True))
    measured = unit in INVARIABLE_UNITS
    text = "–".join(_number(v, measured) for v in shown)
    if unit:
        text += " " + (_plural(unit) if shown[-1] >= 2 else unit)
    return ("≈ " if approx else "") + text

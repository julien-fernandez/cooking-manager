"""Garde-manger : inventaire réel, et différentiel avec un besoin."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from .ingredients import UNIT_ALIASES, normalize_name
from .packaging import TYPICAL_PIECE_GRAMS, TYPICAL_UNIT_EQUIVALENTS, convert_estimated

STATUS_OK = "ok"
STATUS_LOW = "low"
STATUS_OUT = "out"

XSTATUS_MAP = {
    "ok": STATUS_OK,
    "low": STATUS_LOW,
    "urgent": STATUS_LOW,
    "out": STATUS_OUT,
    "a-jeter": STATUS_OUT,
    "à-jeter": STATUS_OUT,
    "perime": STATUS_OUT,
    "périmé": STATUS_OUT,
    "perime-conserve": STATUS_OUT,
    "périmé-conserve": STATUS_OUT,
    "verifier-dlc": STATUS_LOW,
    "vérifier-dlc": STATUS_LOW,
}

ENOUGH = "suffisant"
PARTIAL = "insuffisant"
MISSING = "absent"
UNKNOWN = "inconnu"
STAPLE = "placard"
STAPLE_DOSE_CEILING = 300.0
STAPLE_HINT_SECTIONS = frozenset({
    "Épices & Herbes", "Condiments & Huiles", "Pâtisserie & Levures", "Bouillons & Fonds",
})

PERISHABLE_HINTS = ("frais", "l\u00e9gume", "legume", "fruit", "prot\u00e9ine", "proteine")

DRY_SECTION_PREFIX = "sec"


def is_perishable_section(section: str) -> bool:
    """Un rayon sec ne p\u00e9rit pas, quel que soit le mot que son nom contient (#119)."""
    name = (section or "").strip().lower()
    if name.startswith(DRY_SECTION_PREFIX):
        return False
    return any(h in name for h in PERISHABLE_HINTS)

STALE_AFTER = timedelta(days=14)

NON_PURCHASE: frozenset[str] = frozenset({
    "eau", "eau froide", "eau chaude", "eau bouillante", "eau tiede",
    "gla\u00e7on", "glacon",
})

_UNIT_LOOKUP = {
    variant.lower(): canonical
    for canonical, variants in UNIT_ALIASES.items()
    for variant in variants
}
_UNIT_PATTERN = "|".join(re.escape(v) for v in sorted(_UNIT_LOOKUP, key=len, reverse=True))

_TO_BASE = {"kg": ("g", 1000.0), "g": ("g", 1.0),
            "l": ("ml", 1000.0), "cl": ("ml", 10.0), "ml": ("ml", 1.0),
            "pièce": ("pièce", 1.0)}

_SECTION = re.compile(r"^##+\s+(.+?)\s*$", re.MULTILINE)
_ITEM = re.compile(r"^\s*-\s+(.+?)\s*$", re.MULTILINE)
_STATUS = re.compile(r"#\s*status\s*=\s*([\w\-àéèêëîïôöûü]+)", re.IGNORECASE)
_ENTERED = re.compile(r"entré\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_QTY_IN_TEXT = re.compile(
    rf"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(?:×|x)?\s*(?:(\d+(?:[.,]\d+)?)\s*)?({_UNIT_PATTERN})(?!\w)",
    re.IGNORECASE,
)

_CONTAINERS = (r"sachets?|bo[iî]tes?|pots?|briques?|paquets?|barquettes?|bocal|bocaux"
               r"|bouteilles?|conserves?|flacons?|tubes?")
_PACKS_OF_MEASURE = re.compile(
    rf"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(?:{_CONTAINERS})\s+(?:de\s+)?(\d+(?:[.,]\d+)?)\s*"
    r"(kg|g|cl|ml|l)(?!\w)",
    re.IGNORECASE,
)

@dataclass
class PantryItem:
    rayon: str
    name: str
    name_normalized: str
    qty_text: str = ""
    qty_value: float | None = None
    unit: str | None = None
    status: str = STATUS_OK
    xstatus: str = "ok"
    entered_at: date | None = None
    raw: str = ""
    item_id: int | None = None
    food_key: str | None = None

    @property
    def is_perishable(self) -> bool:
        return is_perishable_section(self.rayon)

@dataclass
class Pantry:
    items: list[PantryItem] = field(default_factory=list)
    updated: date | None = None
    aliases: dict[str, int] = field(default_factory=dict)
    staples: frozenset[str] = field(default_factory=frozenset)

    def age_days(self, today: date | None = None) -> int | None:
        if not self.updated:
            return None
        return ((today or date.today()) - self.updated).days

    def is_stale(self, today: date | None = None) -> bool:
        age = self.age_days(today)
        return age is not None and age > STALE_AFTER.days

    def find(self, normalized: str, food_key: str | None = None) -> PantryItem | None:
        """Appariement par aliment (`food_key`), sinon par nom normalisé avec repli par inclusion de MOT."""
        if not normalized:
            return None
        normalized = normalize_name(normalized)

        if food_key:
            same_food = [i for i in self.items if i.food_key == food_key]
            if same_food:
                return _best(same_food)

        aliased = self.aliases.get(normalized)
        if aliased is not None:
            for item in self.items:
                if item.item_id == aliased:
                    return item

        exact = [i for i in self.items if i.name_normalized == normalized]
        if exact:
            return _best(exact)
        contains = [
            i for i in self.items
            if (_contains_words(i.name_normalized, normalized)
                or _contains_words(normalized, i.name_normalized))
            and not _is_other_food(normalized, i.name_normalized)
            and not _keyed_elsewhere(normalized, i, food_key)
        ]
        if contains:
            return _best(sorted(contains, key=lambda i: len(i.name_normalized)))

        words = _content_words(normalized)
        if not words:
            return None
        loose = [i for i in self.items
                 if words <= _content_words(i.name_normalized)
                 and not _is_other_food(normalized, i.name_normalized)
                 and not _keyed_elsewhere(normalized, i, food_key)]
        if not loose:
            return None
        return _best(sorted(loose, key=lambda i: len(i.name_normalized)))

STOP_WORDS = frozenset({
    "de", "du", "des", "d", "le", "la", "les", "l", "au", "aux", "a",
    "et", "ou", "en", "pour", "avec", "sans", "type", "sorte",
})

def _content_words(text: str) -> frozenset[str]:
    """Les mots porteurs de sens — ceux qui décident de l'identité du produit."""
    return frozenset(w for w in text.split() if w not in STOP_WORDS)

COMPLEMENT_WORDS = frozenset({"de", "du", "des", "d", "a", "au", "aux"})
PROCESSED_HEADS = frozenset({"pate", "farine", "lait", "huile", "sirop", "creme", "beurre"})
FLAVOUR_MARKS = frozenset({"au", "aux", "a"})
DISH_HEADS = frozenset({"gateau", "veloute", "soupe", "biscuit", "chips", "tarte", "plat"})
DISH_TAILS = frozenset({"dessert"})

def _is_other_food(first: str, second: str) -> bool:
    """« lait de coco » (#164), « pâte de lentille », « poivron au piment », « crème dessert » (#203) : autre aliment."""
    for generic, detailed in ((first, second), (second, first)):
        words, base = detailed.split(), generic.split()
        for start in range(len(words) - len(base) + 1):
            if words[start:start + len(base)] == base:
                follower = words[start + len(base)] if start + len(base) < len(words) else None
                if follower in COMPLEMENT_WORDS or follower in DISH_TAILS:
                    return True
                if (start >= 2 and words[start - 1] in COMPLEMENT_WORDS
                        and words[start - 2] in PROCESSED_HEADS):
                    return True
                before = words[:start]
                flavoured = any(w in FLAVOUR_MARKS and before[i + 2:i + 3] != ["choix"]
                                for i, w in enumerate(before[1:]))
                if flavoured or DISH_HEADS.intersection(before):
                    return True
    return False

def _keyed_elsewhere(normalized: str, item: PantryItem, food_key: str | None) -> bool:
    """Une ligne rattachée ne couvre par son nom qu'un besoin SANS aliment qui nomme le sien (#203)."""
    if not item.food_key or food_key:
        return False
    key, need = _content_words(normalize_name(item.food_key)), _content_words(normalized)
    return not (key <= need or need <= key)

def _contains_words(haystack: str, needle: str) -> bool:
    """`needle` apparaît-il dans `haystack` sur des frontières de mot ?"""
    if not needle or not haystack:
        return False
    return re.search(r"(?:^|\s)" + re.escape(needle) + r"(?:\s|$)", haystack) is not None

def _best(candidates: list[PantryItem]) -> PantryItem:
    """Entre plusieurs lignes du même produit, la mieux dotée gagne, chiffrée de préférence."""
    order = {STATUS_OK: 0, STATUS_LOW: 1, STATUS_OUT: 2}
    return sorted(candidates, key=lambda i: (order.get(i.status, 3), i.qty_value is None))[0]

def _parse_qty(text: str) -> tuple[float | None, str | None]:
    """« 2×100 g » → (200, g) · « 3 briques 400 g » → (1200, g) · « en stock » → (None, None)."""
    packed = _PACKS_OF_MEASURE.search(text)
    if packed:
        count = float(packed.group(1).replace(",", "."))
        size = float(packed.group(2).replace(",", "."))
        return count * size, _UNIT_LOOKUP.get(packed.group(3).lower())
    m = _QTY_IN_TEXT.search(text)
    if not m:
        return None, None
    first = float(m.group(1).replace(",", "."))
    second = float(m.group(2).replace(",", ".")) if m.group(2) else None
    unit = _UNIT_LOOKUP.get(m.group(3).lower())
    return (first * second if second else first), unit

QUANTIFIED_STATUSES = frozenset({STATUS_OK, STATUS_LOW})

CONFIRMATION_MAX_AGE = timedelta(days=7)


def entry_quantity(qty_text: str | None, status: str,
                   staple: bool = False) -> tuple[float | None, str | None, str | None]:
    """Quantité d'une entrée au journal, ou le motif pour lequel elle n'en est pas une (#161, ADR 0043)."""
    if status not in QUANTIFIED_STATUSES:
        return None, None, None
    value, unit = _parse_qty(qty_text or "")
    if value is None or unit is None:
        if staple:
            return None, None, None
        return None, None, (
            f"qty_value et unit requis : un '{status}' sans quantité "
            "ne se compare à aucun besoin")
    return value, unit, None


def confirmation_gate(confirmation: dict | None, menu_slug: str) -> dict:
    """Le garde-manger a-t-il été confronté avant que ce panier parte ? (#161)"""
    def refuse(reason: str) -> dict:
        return {"ok": False, "blind": False, "reason": reason, "note": None}

    if confirmation is None:
        return refuse(f"garde-manger non confirmé pour le menu {menu_slug}")
    if confirmation.get("menu_slug") != menu_slug:
        return refuse(
            f"la seule confirmation en base porte sur {confirmation.get('menu_slug')!r}, "
            f"pas sur {menu_slug!r}")

    blind = bool(confirmation.get("blind"))
    reason = (confirmation.get("reason") or "").strip()
    if blind and not reason:
        return refuse("confirmation à l'aveugle sans motif : elle ne dit pas ce qu'on ignore")

    confirmed_at = confirmation.get("confirmed_at")
    if confirmed_at is None:
        return refuse("confirmation sans date : son âge ne se juge pas")
    if date.today() - confirmed_at > CONFIRMATION_MAX_AGE:
        return refuse(
            f"confirmation périmée ({confirmed_at.isoformat()}, "
            f"plus de {CONFIRMATION_MAX_AGE.days} jours)")

    note = None
    if blind:
        note = (f"confirmé À L'AVEUGLE le {confirmed_at.isoformat()} — {reason} : "
                "aucune ligne n'a été regardée")
    return {"ok": True, "blind": blind, "reason": None, "note": note}


_FRONTMATTER_UPDATED = re.compile(
    r"^---\s*$.*?^\s*updated\s*:\s*[\"']?(\d{4}-\d{2}-\d{2})",
    re.MULTILINE | re.DOTALL,
)

def parse_pantry(body: str, updated: date | None = None) -> Pantry:
    """Corps de `Garde-manger.md` → inventaire exploitable."""
    pantry = Pantry(updated=updated)
    if not body:
        return pantry

    if pantry.updated is None:
        fm = _FRONTMATTER_UPDATED.search(body)
        if fm:
            try:
                pantry.updated = date.fromisoformat(fm.group(1))
            except ValueError:
                pantry.updated = None

    sections = list(_SECTION.finditer(body))
    for idx, sec in enumerate(sections):
        rayon = sec.group(1).strip()
        end = sections[idx + 1].start() if idx + 1 < len(sections) else len(body)
        for item in _ITEM.finditer(body[sec.end():end]):
            line = item.group(1).strip()
            if not line or line.startswith(("[", "!", "**Note")):
                continue

            xstatus = "ok"
            sm = _STATUS.search(line)
            if sm:
                xstatus = sm.group(1).strip().lower()
            status = XSTATUS_MAP.get(xstatus, STATUS_OK)

            entered = None
            em = _ENTERED.search(line)
            if em:
                try:
                    entered = date.fromisoformat(em.group(1))
                except ValueError:
                    entered = None

            head = re.split(r"\s+[—–]\s+", line, maxsplit=1)
            name = re.sub(r"\*\*", "", head[0]).strip()
            name = re.sub(r"#\s*status\s*=\s*[\w\-àéèêëîïôöûü]+", "", name)
            name = re.sub(r"\(entré[^)]*\)", "", name)
            name = re.sub(r"\(constaté[^)]*\)", "", name).strip()
            qty_text = head[1] if len(head) > 1 else ""
            qty_text = re.sub(r"#.*$", "", qty_text)
            qty_text = re.sub(r"\(entré[^)]*\)", "", qty_text).strip(" |")

            if not name:
                continue

            qty_value, unit = _parse_qty(qty_text)
            pantry.items.append(PantryItem(
                rayon=rayon, name=name, name_normalized=normalize_name(name),
                qty_text=qty_text, qty_value=qty_value, unit=unit,
                status=status, xstatus=xstatus, entered_at=entered, raw=line,
            ))

    return pantry

@dataclass
class Need:
    """Un ingrédient requis, consolidé sur l'ensemble du menu."""
    name: str
    name_normalized: str
    qty: float | None = None
    unit: str | None = None
    recipes: list[str] = field(default_factory=list)
    is_optional: bool = True
    raw_lines: list[str] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)
    estimate: str | None = None
    food_key: str | None = None
    food_keys: set[str] = field(default_factory=set)

@dataclass
class Verdict:
    need: Need
    outcome: str
    pantry_item: PantryItem | None = None
    reason: str = ""
    to_buy: float | None = None
    assumed_empty: bool = False
    declared: bool = True

def _comparable(need: Need, item: PantryItem) -> bool:
    """Les quantités ne se comparent que si les unités sont commensurables."""
    if need.qty is None or item.qty_value is None:
        return False
    if not need.unit or not item.unit:
        return False
    a, b = _TO_BASE.get(need.unit), _TO_BASE.get(item.unit)
    return bool(a and b and a[0] == b[0])

def _item_base(item: PantryItem) -> tuple[str, float]:
    """L'unité de base du stock : celle de la table, ou son unité propre sans conversion."""
    return _TO_BASE.get(item.unit or "", (item.unit or "", 1.0))

def _typical_key(need: Need) -> str:
    """La clé des tables de poids typique : l'aliment du besoin s'il y figure, sinon son nom."""
    for key in (need.food_key, need.name_normalized):
        if key and (key in TYPICAL_PIECE_GRAMS
                    or any(key == name for name, _ in TYPICAL_UNIT_EQUIVALENTS)):
            return key
    return need.name_normalized

def _estimated_stock(need: Need, item: PantryItem, reserved: float = 0.0) -> float | None:
    """Le stock restant dans l'unité du besoin, sur un poids ou équivalent TYPIQUE — None sans conversion."""
    if need.qty is None or item.qty_value is None or not need.unit or not item.unit:
        return None
    total = convert_estimated(_typical_key(need), item.qty_value, item.unit, need.unit)
    held = (convert_estimated(_typical_key(need), reserved, _item_base(item)[0], need.unit)
            if reserved else 0.0)
    if total is None or held is None:
        return None
    return max(total - held, 0.0)

def _measurable(need: Need, item: PantryItem) -> bool:
    """Directement comparable, ou convertible sur un poids typique."""
    return _comparable(need, item) or _estimated_stock(need, item) is not None

def _reservation(need: Need, item: PantryItem) -> float | None:
    """Ce que ce besoin prélève sur le stock, dans l'unité de base du stock."""
    if need.qty is None or not need.unit:
        return None
    if _comparable(need, item):
        return _to_base(need.qty, need.unit)
    if _estimated_stock(need, item) is None:
        return None
    return convert_estimated(_typical_key(need), need.qty, need.unit, _item_base(item)[0])

_SPOON_SCALE = {"c.s.", "c.c.", "pincée", "trait", "filet", "goutte"}

def _to_base(qty: float, unit: str) -> float:
    return qty * _TO_BASE[unit][1]

def check_needs(needs: list[Need], pantry: Pantry, today: date | None = None) -> list[Verdict]:
    """Les besoins du menu, dans l'ordre, chacun contre le stock que les précédents ont laissé."""
    reserved: dict[int, float] = {}
    verdicts = []
    for need in needs:
        item = pantry.find(need.name_normalized, need.food_key)
        key = id(item)
        verdict = check_need(need, pantry, today, reserved=reserved.get(key, 0.0))
        if item is not None and verdict.outcome in (ENOUGH, PARTIAL):
            want = _reservation(need, item)
            if want is not None:
                reserved[key] = reserved.get(key, 0.0) + want
        verdicts.append(verdict)
    return verdicts

def check_need(need: Need, pantry: Pantry, today: date | None = None,
               reserved: float = 0.0) -> Verdict:
    """Un besoin + l'inventaire, moins ce qu'un autre repas y a déjà `reserved` → un verdict."""
    verdict = _check_need(need, pantry, today, reserved)
    if need.estimate:
        verdict.reason = f"{verdict.reason} ({need.estimate})" if verdict.reason else need.estimate
    beyond = _beyond_staple_dose(need)
    if beyond and need.food_key in pantry.staples:
        verdict.reason = f"{verdict.reason} — dose de basique au-delà de 300 {beyond} : mesurée"
    return verdict

def _beyond_staple_dose(need: Need) -> str | None:
    """L'unité de base (g, ml) d'un besoin qui dépasse le seuil d'un basique, sinon None."""
    if need.qty is None or need.unit not in _TO_BASE:
        return None
    base, factor = _TO_BASE[need.unit]
    if base in ("g", "ml") and need.qty * factor > STAPLE_DOSE_CEILING:
        return base
    return None

def staple_rule_applies(need: Need, pantry: Pantry) -> bool:
    """Vrai si le besoin relève du régime basique : aliment du placard, dose sous le seuil (ADR 0043)."""
    return bool(need.food_key) and need.food_key in pantry.staples and not _beyond_staple_dose(need)

def _staple_verdict(need: Need, pantry: Pantry) -> Verdict | None:
    """Un basique couvre toute dose tant qu'une ligne vit, ou tant qu'aucune ne l'a jamais déclaré (ADR 0043)."""
    if not staple_rule_applies(need, pantry):
        return None
    lines = [i for i in pantry.items if i.food_key == need.food_key]
    if not lines:
        named = pantry.find(need.name_normalized)
        lines = [named] if named is not None and named.food_key is None else []
    live = [i for i in lines if i.status in QUANTIFIED_STATUSES]
    if live:
        return Verdict(need, STAPLE, _best(live), "au placard", 0.0)
    if lines:
        return None
    return Verdict(need, STAPLE, None, "jamais déclaré au garde-manger", 0.0, declared=False)

def staples_undeclared(verdicts: list[Verdict]) -> list[dict]:
    """Les basiques qu'aucune ligne du garde-manger ne porte, un par aliment."""
    seen: dict[str, dict] = {}
    for v in verdicts:
        key = v.need.food_key
        if v.outcome == STAPLE and not v.declared and key and key not in seen:
            seen[key] = {"name": v.need.name, "food_key": key}
    return list(seen.values())

def staples_unlinked(needs: list[Need], pantry: Pantry) -> list[str]:
    """Les besoins sans aliment dont le stock ressemble à un basique : rattachés, ils seraient du placard."""
    out = []
    for need in needs:
        if need.food_key:
            continue
        if need.food_keys & pantry.staples:
            out.append(need.name)
            continue
        item = pantry.find(need.name_normalized)
        if item is not None and (item.food_key in pantry.staples
                                 or item.rayon in STAPLE_HINT_SECTIONS):
            out.append(need.name)
    return out

def _check_need(need: Need, pantry: Pantry, today: date | None, reserved: float) -> Verdict:
    staple = _staple_verdict(need, pantry)
    if staple is not None:
        return staple
    item = pantry.find(need.name_normalized, need.food_key)

    if item is None:
        return Verdict(need, MISSING, None, "absent du garde-manger", need.qty)

    if item.status == STATUS_OUT:
        return Verdict(need, MISSING, item, f"marqué épuisé ({item.xstatus})", need.qty)

    ref = today or date.today()
    if item.is_perishable and item.entered_at is not None:
        item_age = (ref - item.entered_at).days
        if item_age > STALE_AFTER.days:
            return Verdict(
                need, UNKNOWN, item,
                f"produit frais entr\u00e9 il y a {item_age} jours — suppos\u00e9 \u00e9puis\u00e9",
                need.qty, assumed_empty=True,
            )

    if item.is_perishable and item.entered_at is None:
        return Verdict(
            need, UNKNOWN, item,
            "produit frais sans date d'entr\u00e9e — fra\u00eecheur inconnue",
            need.qty, assumed_empty=True,
        )

    if pantry.is_stale(today) and item.is_perishable:
        return Verdict(
            need, UNKNOWN, item,
            f"inventaire vieux de {pantry.age_days(today)} jours — produit frais supposé épuisé",
            need.qty, assumed_empty=True,
        )

    item, uncounted = _pooled(need, item, pantry, ref)
    verdict = _judge(need, item, reserved)
    if uncounted and verdict.outcome == PARTIAL:
        return Verdict(need, UNKNOWN, item,
                       f"{verdict.reason} — sans compter {uncounted} : à confirmer", need.qty)
    return verdict

def _usable_sibling(item: PantryItem, ref: date) -> bool:
    """Une autre ligne du même aliment compte si elle est vivante et, fraîche, entrée depuis moins de STALE_AFTER (14 jours)."""
    if item.status not in QUANTIFIED_STATUSES:
        return False
    if item.is_perishable:
        return item.entered_at is not None and (ref - item.entered_at).days <= STALE_AFTER.days
    return True

def _pooled(need: Need, item: PantryItem, pantry: Pantry, ref: date) -> tuple[PantryItem, str]:
    """Les lignes vivantes du même aliment s'additionnent (#187) ; rend aussi celles qu'on n'a pas pu compter."""
    if not item.food_key or item.qty_value is None or not item.unit:
        return item, ""
    siblings = [i for i in pantry.items
                if i is not item and i.food_key == item.food_key and _usable_sibling(i, ref)]
    if not siblings:
        return item, ""
    base, factor = _item_base(item)
    total, texts, uncounted = item.qty_value * factor, [item.qty_text or item.name], []
    food = _typical_key(need)
    states = _states(item.name_normalized)
    for other in siblings:
        clash = _state_clash(states, _states(other.name_normalized))
        if clash:
            uncounted.append(f"{other.name}, d'un autre état ({clash})")
            continue
        added = _in_base(food, other, base)
        if added is None:
            uncounted.append(f"{other.name} ({other.qty_text or 'quantité non chiffrée'}), "
                             "dont la quantité ne se compare pas")
        else:
            total += added
            texts.append(other.qty_text or other.name)
    if len(texts) == 1:
        return item, " ; ".join(uncounted)
    return replace(item, qty_value=total, unit=base, qty_text=" + ".join(texts)), " ; ".join(uncounted)

STATE_AXES = (
    {"cru": "cru", "crue": "cru", "cuit": "cuit", "cuite": "cuit"},
    {"frais": "frais", "fraiche": "frais", "sec": "sec", "seche": "sec", "sechee": "sec",
     "surgele": "surgelé", "surgelee": "surgelé", "fume": "fumé", "fumee": "fumé"},
)

def _states(name_normalized: str) -> list[str | None]:
    """L'état déclaré par un nom sur chaque axe (cuisson, conservation), None s'il n'en dit rien."""
    words = name_normalized.split()
    return [next((axis[w] for w in words if w in axis), None) for axis in STATE_AXES]

def _state_clash(first: list[str | None], second: list[str | None]) -> str:
    """« cuit ≠ cru » quand deux lignes déclarent un état différent sur un même axe (#202) ; un état tu ne contredit rien."""
    return ", ".join(f"{a} ≠ {b}" for a, b in zip(first, second, strict=True) if a and b and a != b)

def _in_base(food: str, item: PantryItem, base: str) -> float | None:
    """La quantité d'une ligne dans l'unité de base voulue : par la table, sinon par un poids typique."""
    if item.qty_value is None or not item.unit:
        return None
    unit_base, factor = _item_base(item)
    if unit_base == base:
        return item.qty_value * factor
    return convert_estimated(food, item.qty_value, item.unit, base)

def _judge(need: Need, item: PantryItem, reserved: float) -> Verdict:
    if item.status == STATUS_LOW and not _measurable(need, item):
        return Verdict(need, PARTIAL, item, f"stock faible ({item.xstatus})", need.qty)

    if item.status == STATUS_OK and need.unit in _SPOON_SCALE:
        return Verdict(need, ENOUGH, item,
                       f"présent en stock ({item.qty_text or 'quantité non chiffrée'}) — "
                       f"un besoin de {need.qty} {need.unit} s'y prélève")

    if need.qty is None:
        return Verdict(need, ENOUGH, item,
                       f"présent en stock ({item.qty_text or 'quantité non chiffrée'})")

    if not _comparable(need, item):
        have_est = _estimated_stock(need, item, reserved)
        if have_est is not None:
            return _verdict_estimated(need, item, have_est, reserved)
        return Verdict(
            need, UNKNOWN, item,
            f"présent ({item.qty_text or 'quantité non chiffrée'}) — "
            f"besoin de {need.qty} {need.unit or ''}, comparaison impossible".strip(),
        )

    have = max(_to_base(item.qty_value, item.unit) - reserved, 0.0)  # type: ignore[arg-type]
    want = _to_base(need.qty, need.unit)            # type: ignore[arg-type]
    shared = (f", dont {round(reserved)} {_TO_BASE[item.unit][0]} réservé"  # type: ignore[index]
              f" par un autre repas") if reserved else ""
    if have >= want:
        return Verdict(need, ENOUGH, item, f"{item.qty_text} en stock{shared}, suffisant")

    remaining = want - have
    factor = _TO_BASE[need.unit][1]                 # type: ignore[index]
    return Verdict(
        need, PARTIAL, item,
        f"{item.qty_text} en stock{shared}, il en manque",
        round(remaining / factor, 2),
    )

def _verdict_estimated(need: Need, item: PantryItem, have: float, reserved: float) -> Verdict:
    """Besoin et stock d'unités différentes, comparés après conversion du stock — et le dit."""
    if need.unit == item.unit:
        return _plain_verdict(need, item, have, reserved)
    in_need_unit = convert_estimated(_typical_key(need), item.qty_value or 0.0,
                                     item.unit or "", need.unit or "") or 0.0
    weighed = {"g", "kg"} & {need.unit, item.unit}
    label = "poids estimé" if weighed else "équivalent estimé"
    note = f"{label} : {item.qty_text} ≈ {_pretty(in_need_unit)} {need.unit}"
    shared = ", dont une part réservée par un autre repas" if reserved else ""
    want = need.qty or 0.0
    if have >= want:
        return Verdict(need, ENOUGH, item, f"{item.qty_text} en stock{shared}, suffisant ({note})")
    return Verdict(need, PARTIAL, item, f"{item.qty_text} en stock{shared}, il en manque ({note})",
                   round(want - have, 2))

def _plain_verdict(need: Need, item: PantryItem, have: float, reserved: float) -> Verdict:
    """Deux quantités de la même unité hors table : comparées telles quelles, rien n'est estimé."""
    shared = f", dont {round(reserved)} {need.unit} réservé par un autre repas" if reserved else ""
    want = need.qty or 0.0
    if have >= want:
        return Verdict(need, ENOUGH, item, f"{item.qty_text} en stock{shared}, suffisant")
    return Verdict(need, PARTIAL, item, f"{item.qty_text} en stock{shared}, il en manque",
                   round(want - have, 2))

def _pretty(value: float) -> str:
    return str(int(value)) if value == int(value) else str(round(value, 2))

def build_needs(meals_recipes: list[tuple[str, list, float]]) -> list[Need]:
    """Consolide les ingr\u00e9dients de plusieurs recettes en besoins uniques."""
    needs: dict[tuple[str, str], Need] = {}
    for title, ingredients, ratio in meals_recipes:
        for raw_ing in ingredients:
            ing = _as_mapping(raw_ing)
            key = ing.get("name_normalized") or normalize_name(ing.get("name", ""))
            if not key or key in NON_PURCHASE:
                continue

            unit = ing.get("unit")
            family = _TO_BASE[unit][0] if unit in _TO_BASE else (unit or "")
            need = needs.get((key, family))
            if need is None:
                need = Need(name=ing.get("name", ""), name_normalized=key, unit=unit,
                            food_key=ing.get("food_key") or None)
                needs[(key, family)] = need
            elif need.food_key != (ing.get("food_key") or None):
                need.food_key = None
            if ing.get("food_key"):
                need.food_keys.add(ing["food_key"])

            qty = ing.get("qty_max") or ing.get("qty_min")
            if qty is not None:
                base_unit, factor = _TO_BASE.get(unit, (unit, 1.0)) if unit else (unit, 1.0)
                if need.unit is None or need.qty is None:
                    need.unit = base_unit
                need.qty = (need.qty or 0) + float(qty) * factor * ratio

            if not ing.get("is_optional"):
                need.is_optional = False
            if title not in need.recipes:
                need.recipes.append(title)
            if not ing.get("parsed") and ing.get("raw"):
                need.raw_lines.append(ing["raw"])

    merged = _merge_equivalent_needs(needs)
    return sorted(merged, key=lambda n: (n.is_optional, n.name))

def _merge_equivalent_needs(needs: dict[tuple[str, str], Need]) -> list[Need]:
    """Deux libellés d'un même aliment font un seul besoin."""
    by_family: dict[str, list[Need]] = {}
    for (_, family), need in needs.items():
        by_family.setdefault(family, []).append(need)

    kept: list[Need] = []
    for family_needs in by_family.values():
        survivors: list[Need] = []
        for need in sorted(family_needs, key=lambda n: len(n.name_normalized)):
            host = next(
                (s for s in survivors if _same_food(s.name_normalized, need.name_normalized)),
                None,
            )
            if host is None:
                survivors.append(need)
                continue
            _absorb(host, need)
        kept.extend(survivors)
    return _merge_pieces_into_weight(kept)

def _merge_pieces_into_weight(needs: list[Need]) -> list[Need]:
    """Un aliment à poids typique, demandé en g et en pièces, fait UN besoin en g."""
    for name, each in TYPICAL_PIECE_GRAMS.items():
        weight = next((n for n in needs if _typical_key(n) == name and n.unit == "g"), None)
        pieces = next((n for n in needs if _typical_key(n) == name and n.unit == "pièce"), None)
        if weight is None or pieces is None or pieces.qty is None:
            continue
        count = pieces.qty
        pieces.qty, pieces.unit = count * each, "g"
        _absorb(weight, pieces)
        weight.merged_from.remove(pieces.name)
        weight.estimate = f"poids estimé : {_pretty(count)} pièce × {_pretty(each)} g"
        needs = [n for n in needs if n is not pieces]
    return needs

def _same_food(generic: str, detailed: str) -> bool:
    """`detailed` est-il le même aliment que `generic`, en plus qualifié ?"""
    if not generic or not detailed or _is_other_food(generic, detailed):
        return False
    return (
        _contains_words(detailed, generic)
        or _content_words(generic) <= _content_words(detailed)
    )

def _absorb(host: Need, other: Need) -> None:
    """Verser un besoin dans un autre, sans rien perdre de traçable."""
    if other.qty is not None:
        host.qty = (host.qty or 0) + other.qty
        if host.unit is None:
            host.unit = other.unit
    if not other.is_optional:
        host.is_optional = False
    for recipe in other.recipes:
        if recipe not in host.recipes:
            host.recipes.append(recipe)
    if host.food_key != other.food_key:
        host.food_key = None
    host.food_keys |= other.food_keys
    host.raw_lines.extend(other.raw_lines)
    host.merged_from.append(other.name)
    host.merged_from.extend(other.merged_from)

def _as_mapping(ing) -> dict:
    """Accepte indifféremment une ligne de DB (mapping) et un `Ingredient`."""
    if hasattr(ing, "get"):
        return ing
    return {
        "name": getattr(ing, "name", ""),
        "name_normalized": getattr(ing, "name_normalized", "") or "",
        "qty_min": getattr(ing, "qty_min", None),
        "qty_max": getattr(ing, "qty_max", None),
        "unit": getattr(ing, "unit", None),
        "is_optional": getattr(ing, "is_optional", False),
        "parsed": getattr(ing, "parsed", True),
        "raw": getattr(ing, "raw", ""),
        "food_key": getattr(ing, "food_key", None),
    }

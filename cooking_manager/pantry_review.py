"""Les lignes du garde-manger sur lesquelles la liste compte (spec 01 § 8.2)."""

from __future__ import annotations

from cooking_manager.pantry import ENOUGH, PARTIAL, UNKNOWN

OUTCOMES_NEEDING_A_LOOK = (ENOUGH, PARTIAL, UNKNOWN)


def review_lines(lines: list[dict]) -> list[dict]:
    """Un article par entrée, avec tous les besoins qu'il couvre ; `inconnu` demande sa quantité."""
    by_item: dict[int, dict] = {}
    for ln in lines:
        item = ln.get("pantry")
        if item is None or ln["outcome"] not in OUTCOMES_NEEDING_A_LOOK:
            continue
        entry = by_item.setdefault(item["id"], {
            "id": item["id"], "name": item["name"], "qty_text": item["qty_text"] or "",
            "status": item["status"], "section": "", "ask_qty": False, "needs": []})
        entry["needs"].append({"name": ln["name"], "qty": ln["qty"], "unit": ln["unit"],
                               "recipes": ln["recipes"], "outcome": ln["outcome"]})
        entry["ask_qty"] = entry["ask_qty"] or ln["outcome"] == UNKNOWN
    return list(by_item.values())

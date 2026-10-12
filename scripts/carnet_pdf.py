"""Carnet de la semaine : chaque repas du menu, sa fiche à la tablée réelle (`portions`), en PDF via Chromium."""

import argparse
import html
import json
import subprocess
import tempfile
import urllib.request
from datetime import date
from pathlib import Path

from cooking_manager.quantity_display import format_quantity

MEDIA = Path(__file__).resolve().parents[1] / "web" / "media" / "recipes"
SLOTS = {"breakfast": "Petit-déjeuner", "lunch": "Déjeuner", "snack": "Goûter", "dinner": "Dîner"}
DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.load(r)


def qty_text(ing, mult):
    return format_quantity(ing["qty_min"], ing["qty_max"], ing["unit"], mult)


def ingredient_lines(recipe, portions):
    base = recipe["servings"] or 0
    ratio = portions / base if base and portions else 1
    replaced = {}
    for i in recipe["ingredients"]:
        if i["for_person_id"] and i["replaces_position"]:
            replaced[i["replaces_position"]] = replaced.get(i["replaces_position"], 0) + 1
    lines = []
    for i in recipe["ingredients"]:
        mult = ratio
        if i["for_person_id"]:
            mult = 1
        elif portions and replaced.get(i["position"]) and base:
            mult = max(portions - replaced[i["position"]], 0) / base
        name = i["name"] if i["parsed"] else i["raw"]
        if i["is_optional"]:
            name += " (optionnel)"
        if i["for_person_id"]:
            name += f" — portion de {i['for_person'] or 'convive'}"
        lines.append((qty_text(i, mult), name))
    return lines


def split_staples(recipe, portions):
    ordinary, basics = [], []
    for ing, line in zip(recipe["ingredients"], ingredient_lines(recipe, portions), strict=True):
        (basics if ing.get("pantry_staple") else ordinary).append(line)
    return ordinary, basics


def staples_line(basics):
    if not basics:
        return ""
    items = " · ".join(html.escape(f"{q} {name}".strip()) for q, name in basics)
    return f"<p class='placard'><b>Du placard :</b> {items}</p>"


def meal_html(meal, recipe, photo=None):
    e = html.escape
    head = f"<h3>{e(SLOTS.get(meal['slot']) or meal['slot'])} · {e(meal['dish'])}</h3>"
    who = ", ".join(meal["eaters"] or [])
    if meal["match_kind"] == "leftovers":
        return head + "<p class='note'>Restes : rien à cuisiner.</p>"
    if recipe is None:
        return head + "<p class='note'>Sans fiche.</p>"
    meta = f"{meal['portions']} portions ({e(who)})" if meal["portions"] else ""
    if recipe.get("total_time_min"):
        meta += f" · {recipe['total_time_min']} min"
    img = f"<img class='photo' src='{e(photo)}' alt=''>" if photo else ""
    ordinary, basics = split_staples(recipe, meal["portions"])
    out = head + img + f"<p class='meta'>{meta}</p><ul>"
    for q, name in ordinary:
        out += f"<li><b>{e(q)}</b> {e(name)}</li>"
    out += "</ul>" + staples_line(basics) + "<ol>" + "".join(f"<li>{e(s['text'])}</li>" for s in recipe["steps"]) + "</ol>"
    return out


def photo_src(base, recipe):
    local = MEDIA / f"{recipe['slug']}.jpg"
    if local.exists():
        return local.resolve().as_uri()
    url = recipe.get("photo_url") or ""
    return base + url if url.startswith("/") else url or None


def build(base, slug):
    meals = get(base, f"/api/menus/{slug}/meals")["meals"]
    order = list(SLOTS)
    meals.sort(key=lambda m: (m["day"], order.index(m["slot"]) if m["slot"] in order else 9))
    recipes = {}
    body = f"<h1>Carnet de la semaine</h1><p class='meta'>{html.escape(slug)}</p>"
    day = None
    for m in meals:
        if m["served"]:
            continue
        if m["day"] != day:
            day = m["day"]
            d = date.fromisoformat(day)
            body += f"<h2>{DAYS[d.weekday()]} {d.day:02d}/{d.month:02d}</h2>"
        slug_r = m["recipe_slug"]
        if slug_r and slug_r not in recipes:
            recipes[slug_r] = get(base, f"/api/recipes/{slug_r}")
        body += f"<section>{meal_html(m, recipes.get(slug_r),
                                             photo_src(base, recipes[slug_r]) if slug_r else None)}</section>"
    css = """body{font:11pt/1.4 Georgia,serif;margin:0 1.2cm;color:#222}
h1{letter-spacing:.06em}h2{border-bottom:1px solid #999;margin-top:1.4em;letter-spacing:.08em;page-break-after:avoid}
h3{margin:.9em 0 .2em}section{page-break-inside:avoid}.meta,.note{color:#666;margin:0 0 .3em}
section{overflow:hidden}.photo{float:right;width:4.5cm;height:3.4cm;object-fit:cover;margin:.2em 0 .4em .8em;border-radius:3px}
ul{columns:2;margin:.2em 0}ol{margin:.3em 0}li{margin:.1em 0}
.placard{font-size:10pt;color:#555;margin:.2em 0 .6em}"""
    return f"<!doctype html><meta charset='utf-8'><title>Carnet {html.escape(slug)}</title><style>{css}</style>{body}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("menu_slug")
    p.add_argument("out", type=Path)
    p.add_argument("--base-url", default="http://localhost:8795")
    a = p.parse_args()
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(build(a.base_url, a.menu_slug))
    subprocess.run(["chromium", "--headless", "--no-pdf-header-footer",
                    f"--print-to-pdf={a.out.resolve()}", f.name], check=True, capture_output=True)
    print(a.out)


if __name__ == "__main__":
    main()

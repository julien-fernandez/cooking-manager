"""Rattrapage du placard (ADR 0043) : propose les aliments à marquer, puis les crée et rattache après validation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cooking_manager.ingredients import normalize_name  # noqa: E402
from cooking_manager.pantry import STAPLE_HINT_SECTIONS  # noqa: E402

API = "http://127.0.0.1:8795"

def group_candidates(rows: list[dict]) -> list[dict]:
    """Les lignes des rayons du placard, groupées par aliment visé : le sien s'il existe, sinon son nom."""
    groups: dict[str, dict] = {}
    for r in rows:
        if r["section"] not in STAPLE_HINT_SECTIONS:
            continue
        key = r["food_key"] or normalize_name(r["name"])
        group = groups.setdefault(key, {
            "accept": False, "food_key": key, "food_name": r["name"],
            "exists": bool(r["food_key"]), "pantry_names": [], "refs": []})
        group["pantry_names"].append(r["name"])
        if r["name_normalized"] not in group["refs"]:
            group["refs"].append(r["name_normalized"])
    return list(groups.values())

def ingredient_refs(groups: list[dict], ingredient_names: list[str]) -> None:
    """Ajoute aux refs les noms d'ingrédients qui commencent par la clé de l'aliment."""
    for group in groups:
        for name in ingredient_names:
            if (name == group["food_key"] or name.startswith(group["food_key"] + " ")) \
                    and name not in group["refs"]:
                group["refs"].append(name)

async def propose(out: Path) -> None:
    import asyncpg

    from backend.config import DATABASE_DSN

    conn = await asyncpg.connect(DATABASE_DSN)
    try:
        rows = [dict(r) for r in await conn.fetch(
            "SELECT name, name_normalized, food_key, section FROM pantry_item ORDER BY section, name")]
        names = [r["name_normalized"] for r in await conn.fetch(
            "SELECT DISTINCT name_normalized FROM recipe_ingredient WHERE food_key IS NULL")]
    finally:
        await conn.close()
    groups = group_candidates(rows)
    ingredient_refs(groups, names)
    out.write_text(json.dumps(groups, ensure_ascii=False, indent=1))
    print(f"{len(groups)} aliment(s) proposés → {out} (passer `accept` à true après validation)")

async def apply(path: Path) -> None:
    import httpx

    groups = [g for g in json.loads(path.read_text()) if g.get("accept")]
    failed: list[str] = []
    async with httpx.AsyncClient(base_url=API, timeout=60) as client:
        for g in groups:
            if g["exists"]:
                food = (await client.get(f"/api/food/{g['food_key']}")).json()
                body = {k: food.get(k) for k in ("name", "category", "kind", "ciqual_code", "conservation")}
                r = await client.put(f"/api/food/{g['food_key']}", json={**body, "pantry_staple": True})
            else:
                r = await client.post("/api/food", json={"key": g["food_key"], "name": g["food_name"],
                                                         "pantry_staple": True, "source": "staples-backfill"})
            if r.status_code >= 400:
                failed.append(f"{g['food_key']} : {r.status_code} {r.text[:120]}")
        await client.post("/api/arbitration/refresh", params={"subject": "food_key"})
        for g in groups:
            for ref in g["refs"]:
                r = await client.post("/api/arbitration/decisions", json={
                    "decided_by": "staples-backfill",
                    "decisions": [{"subject": "food_key", "ref": ref, "decision": g["food_key"]}]})
                if r.status_code >= 400:
                    failed.append(f"{ref} → {g['food_key']} : {r.status_code} {r.text[:120]}")
    print(f"{len(groups)} aliment(s) marqués ; {len(failed)} échec(s)")
    for line in failed:
        print("  -", line)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("propose").add_argument("out", type=Path)
    sub.add_parser("apply").add_argument("path", type=Path)
    args = parser.parse_args()
    asyncio.run(propose(args.out) if args.cmd == "propose" else apply(args.path))

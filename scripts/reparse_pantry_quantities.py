"""Relit `qty_text` des lignes vivantes du garde-manger avec le parseur courant : « 3 briques 400 g » → 1200 g (#187)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import DATABASE_DSN  # noqa: E402
from cooking_manager.pantry import entry_quantity  # noqa: E402

async def main(apply: bool) -> None:
    import asyncpg

    conn = await asyncpg.connect(DATABASE_DSN)
    try:
        rows = await conn.fetch(
            """SELECT id, name, qty_text, qty_value, unit, status FROM pantry_item
                WHERE status IN ('ok', 'low') AND qty_text <> '' ORDER BY id""")
        changes = []
        for r in rows:
            value, unit, refusal = entry_quantity(r["qty_text"], r["status"])
            old = float(r["qty_value"]) if r["qty_value"] is not None else None
            if refusal is None and (value, unit) != (old, r["unit"]):
                changes.append((r["id"], r["name"], r["qty_text"], old, r["unit"], value, unit))
        for id_, name, text, old, old_unit, value, unit in changes:
            print(f"{id_:>6} | {name} | « {text} » : {old} {old_unit} → {value} {unit}")
        print(f"{len(changes)} ligne(s) à relire sur {len(rows)}")
        if apply and changes:
            async with conn.transaction():
                await conn.executemany(
                    "UPDATE pantry_item SET qty_value = $2, unit = $3 WHERE id = $1",
                    [(c[0], c[5], c[6]) for c in changes])
            print("appliqué")
    finally:
        await conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="écrire (sinon : liste seulement)")
    asyncio.run(main(parser.parse_args().apply))

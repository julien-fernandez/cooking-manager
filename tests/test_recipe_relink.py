"""Une fiche réécrite reprend les rattachements déjà tranchés à l'arbitrage (2026-10-05)."""

import asyncio

from backend.ingest import write_recipe_ingredients
from cooking_manager.ingredients import parse_ingredient


class _Conn:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        return [{"id": 3, "name": "Claire"}]

    async def execute(self, sql, *args):
        self.executed.append((" ".join(sql.split()), args))
        return "OK"


def test_les_decisions_settled_reviennent_apres_l_ecriture():
    conn = _Conn()
    asyncio.run(write_recipe_ingredients(conn, 4177, [parse_ingredient("4 courgettes", 1)]))

    statements = [sql for sql, _ in conn.executed]
    insert = next(i for i, sql in enumerate(statements) if sql.startswith("INSERT INTO recipe_ingredient"))
    relink = [i for i, sql in enumerate(statements)
              if sql.startswith("UPDATE recipe_ingredient") and "arbitration" in sql]
    assert relink and relink[0] > insert, "sans ce relink, un PUT efface tous les food_key de la fiche"
    sql, args = conn.executed[relink[0]]
    assert "status = 'settled'" in sql and "decision IS NOT NULL" in sql and args == (4177,)

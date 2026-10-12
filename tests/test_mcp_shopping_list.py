"""L'outil MCP ne remplace pas la tablée réelle par 4 couverts — menu du 05/10."""

import pytest

cooking_mcp = pytest.importorskip("backend.cooking_mcp")


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def fake_api(method, path, body=None):
        seen.append(path)
        return {}

    monkeypatch.setattr(cooking_mcp, "_api", fake_api)
    return seen


def _tool(name):
    tool = getattr(cooking_mcp, name)
    return getattr(tool, "fn", tool)


@pytest.mark.asyncio
async def test_sans_couverts_la_liste_suit_la_tablee(calls):
    await _tool("shopping_list")("2026-10-05_semaine")
    assert calls == ["/api/menus/2026-10-05_semaine/shopping-list"]


@pytest.mark.asyncio
async def test_des_couverts_demandes_passent_tels_quels(calls):
    await _tool("shopping_list")("2026-10-05_semaine", covers=6)
    assert calls == ["/api/menus/2026-10-05_semaine/shopping-list?covers=6"]

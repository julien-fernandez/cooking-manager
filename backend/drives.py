"""Multi-store product search — Drive B behind a common interface."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, asdict

log = logging.getLogger(__name__)

SUPPORTED_STORES = ("drive_b",)

@dataclass
class StoreProduct:
    product_id: str
    name: str
    brand: str
    image_url: str
    price: float | None
    price_per_unit: str
    nutriscore: str
    store: str
    offer_id: str = ""

async def search_store(store: str, query: str, limit: int = 5) -> list[StoreProduct]:
    if store == "drive_b":
        return await _search_drive_b(query, limit)
    raise ValueError(f"Enseigne inconnue : {store}")

async def map_ingredients(
    store: str,
    ingredients: list[dict],
    concurrency: int = 3,
) -> list[dict]:
    """Batch: search best product match for each ingredient, in parallel."""
    sem = asyncio.Semaphore(concurrency)

    async def _one(ing: dict) -> dict:
        query = ing.get("name_normalized") or ing["name"]
        async with sem:
            try:
                results = await search_store(store, query)
            except Exception as exc:
                log.warning("search failed for %r on %s: %s", query, store, exc)
                results = []
        return {
            "ingredient": ing["name"],
            "qty": ing.get("qty"),
            "unit": ing.get("unit"),
            "recipes": ing.get("recipes", []),
            "results": [asdict(p) for p in results],
            "selected": 0 if results else -1,
        }

    return list(await asyncio.gather(*[_one(i) for i in ingredients]))

async def _search_drive_b(query: str, limit: int = 5) -> list[StoreProduct]:
    """Adaptateur prive (API non documentee de l'enseigne) : non publie."""
    log.warning("adaptateur drive prive absent de la version publique")
    return []

def _parse_price(raw: str) -> float | None:
    try:
        return float(
            raw.replace("\xa0", "").replace("€", "")
            .replace(",", ".").strip()
        )
    except (ValueError, AttributeError):
        return None

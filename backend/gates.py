"""Le moteur de gates côté I/O : charger depuis la base, évaluer, journaliser, refuser (spec 01)."""

from __future__ import annotations

import datetime
import json
from collections.abc import Awaitable
from typing import Any

from fastapi import HTTPException

from cooking_manager import gates as g


async def _safe(awaitable: Awaitable[Any]) -> Any:
    """Un handler qui lève devient une `LoadError` : son gate sera non mesuré, pas la route en 500."""
    try:
        return await awaitable
    except HTTPException as exc:
        return g.LoadError(f"HTTP {exc.status_code} : {exc.detail}")
    except Exception as exc:  # noqa: BLE001
        return g.LoadError(f"{type(exc).__name__}: {exc}")


def decode_verdict_row(row: Any) -> dict[str, Any]:
    """Une ligne du journal en types JSON : NUMERIC, JSONB et TIMESTAMPTZ ne sortent pas tels quels."""
    detail = row["detail"]
    return {"state": row["state"],
            "value": float(row["value"]) if row["value"] is not None else None,
            "detail": json.loads(detail) if isinstance(detail, str) else (detail or {}),
            "cart_fingerprint": row["cart_fingerprint"],
            "measured_at": row["measured_at"].isoformat()}


async def _pending_refs(conn: Any, shopping: Any) -> Any:
    """Les aliments des courses encore en file d'arbitrage ; des courses illisibles restent illisibles."""
    if isinstance(shopping, g.LoadError):
        return shopping
    refs = sorted({line["name_normalized"] for line in shopping["lines"]})
    rows = await conn.fetch(
        """SELECT ref FROM arbitration
            WHERE subject = 'food_key' AND status = 'pending' AND ref = ANY($1::text[])""",
        refs)
    return [r["ref"] for r in rows]


WINDOW_REASON = "les repas passés ne sont pas jugés avant la spec 04 (passé = mangé)"


def _today() -> str:
    """Le jour où commence la fenêtre : celui du serveur, comme le reste de l'app."""
    return datetime.date.today().isoformat()


async def load_inputs(slug: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Les entrées de chaque gate, lues de la base ou des handlers existants — rien n'est stocké."""
    from backend import app as api

    today = _today()
    pool = await api.get_pool(api.DATABASE_DSN)
    async with pool.acquire() as conn:
        menu = await conn.fetchrow("SELECT id, status FROM menu WHERE slug = $1", slug)
        if menu is None:
            raise HTTPException(404, f"Menu introuvable : {slug}")
        days = [r["day"] for r in await conn.fetch(
            """SELECT DISTINCT day FROM menu_meal
                WHERE menu_id = $1 AND day IS NOT NULL ORDER BY day""", menu["id"])
            if r["day"].isoformat() >= today]
        synced = {r["week_monday"] for r in await conn.fetch(
            "SELECT week_monday FROM child_week_presence")}
        active = await conn.fetchval("SELECT count(*) FROM menu WHERE status = 'active'")
        last_verify = await conn.fetchrow(
            """SELECT state, value, detail, cart_fingerprint, measured_at FROM gate_verdict
                WHERE menu_slug = $1 AND gate_id = 'verify_missing' AND transition = 'verify'
                ORDER BY measured_at DESC, id DESC LIMIT 1""", slug)
        cart_rows = await conn.fetch(
            "SELECT id, status, quantity FROM cart_item WHERE menu_slug = $1", slug)
        latest = await conn.fetch(
            """SELECT DISTINCT ON (gate_id) gate_id, outcome, state, override_reason
                 FROM gate_verdict WHERE menu_slug = $1 AND transition <> 'verify'
                ORDER BY gate_id, measured_at DESC, id DESC""", slug)

        shopping = await _safe(api.menu_shopping_list(slug, from_date=today))
        pending = await _safe(_pending_refs(conn, shopping))

    compat = await _safe(api.menu_compatibility(slug, from_date=today))
    confirmation = await _safe(api._confirmation_state(slug))
    cart = await _safe(api.read_cart(slug))

    unsynced = [d.isoformat() for d in days
                if d - datetime.timedelta(days=d.weekday()) not in synced]
    inputs: dict[str, Any] = {
        "tablee_unresolved": {"days": [d.isoformat() for d in days], "unsynced": unsynced},
        "slots_uncomposed": shopping,
        "meals_orphan": shopping,
        "conflicts_uncovered": compat,
        "parts_unmentioned": compat,
        "pantry_blind": confirmation,
        "food_pending": pending,
        "cart_asked": cart,
        "cart_stale": cart,
        "verify_missing": {
            "last": decode_verdict_row(last_verify) if last_verify else None,
            "fingerprint": g.cart_fingerprint(dict(r) for r in cart_rows)},
        "published": {"status": menu["status"], "active_menus": active},
    }
    return inputs, g.forced_reasons(latest)


async def evaluate(slug: str) -> tuple[dict[str, Any], dict[str, g.GateResult]]:
    """Une seule fonction pour `/gates` et pour le 409 : l'iPad et l'agent lisent la même vérité."""
    inputs, forced = await load_inputs(slug)
    results = {gate.id: g.run(gate, inputs.get(gate.id)) for gate in g.GATES}
    now = datetime.datetime.now(datetime.UTC).isoformat()
    window = {"from_date": _today(), "reason": WINDOW_REASON}
    return g.report(slug, results, forced, now, window=window), results


ACTORS = ("agent", "ipad")

def _check_actor(actor: str) -> None:
    """L'acteur se juge avant toute écriture : le CHECK SQL ferait un 500."""
    if actor not in ACTORS:
        raise HTTPException(422, f"actor inconnu : {actor} (attendu {list(ACTORS)})")


_INSERT ="""INSERT INTO gate_verdict
                 (menu_slug, gate_id, transition, state, value, threshold, detail, outcome,
                  override_reason, actor, cart_fingerprint)
             VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11)"""


async def journal(slug: str, transition: str, results: list[g.GateResult], outcome: str,
                  override_reason: str | None, actor: str,
                  fingerprint: str | None = None) -> None:
    """Le journal ne fait qu'ajouter : un refus rouge reste sur le disque (principe 6)."""
    from backend import app as api

    pool = await api.get_pool(api.DATABASE_DSN)
    async with pool.acquire() as conn:
        await conn.executemany(_INSERT, [
            (slug, r.id, transition, r.state, r.value, r.threshold,
             json.dumps(r.detail, default=str), outcome, override_reason, actor, fingerprint)
            for r in results])


async def record_verify(slug: str, payload: dict, actor: str = "agent") -> g.GateResult:
    """Le gate 9 se mesure quand le panier est lu, avec l'empreinte de ce panier-là."""
    from backend import app as api

    _check_actor(actor)
    result = g.verify_measure(payload)
    pool = await api.get_pool(api.DATABASE_DSN)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, status, quantity FROM cart_item WHERE menu_slug = $1", slug)
        await conn.executemany(_INSERT, [
            (slug, result.id, "verify", result.state, result.value, result.threshold,
             json.dumps(result.detail, default=str), "mesuré", None, actor,
             g.cart_fingerprint(dict(r) for r in rows))])
    return result


async def require_gates(slug: str, transition: str, override_reason: str = "",
                        actor: str = "agent") -> None:
    """409 si un gate exigé n'est pas vert ; un motif écrit fait passer, et se journalise."""
    _check_actor(actor)
    _, results = await evaluate(slug)
    decision = g.decide(transition, results)
    reason = (override_reason or "").strip()
    outcome = "passé" if decision["allowed"] else ("forcé" if reason else "refusé")
    required = [results[gate.id] for gate in g.required_gates(transition) if gate.wired]
    await journal(slug, transition, required, outcome, reason or None, actor)
    if outcome == "refusé":
        raise HTTPException(409, {
            "error": "gate", "transition": transition,
            "red": [r.as_dict() for r in decision["red"]],
            "not_wired": decision["not_wired"],
            "hint": f"réparer les gates rouges (GET /api/menus/{slug}/gates), ou passer "
                    "override_reason : il se journalise et l'étape s'affichera « forcé »"})

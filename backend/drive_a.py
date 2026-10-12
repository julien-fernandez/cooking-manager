"""Le drive vu par l'application : façade REST loopback de drive-a-connector (#156)."""

from __future__ import annotations

import logging

import httpx

from cooking_manager.election import Offer

from .config import DRIVE_A_REST_URL, DRIVE_A_TIMEOUT

logger = logging.getLogger("cooking.drive_a")


class DriveUnreachable(RuntimeError):
    """Le drive n'a pas répondu — jamais à confondre avec « il n'y a rien »."""


async def _call(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{DRIVE_A_REST_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=DRIVE_A_TIMEOUT) as client:
            response = await client.request(method, url, json=payload)
    except httpx.HTTPError as exc:
        raise DriveUnreachable(f"{method} {path} : {exc}") from exc
    if response.status_code >= 400:
        raise DriveUnreachable(
            f"{method} {path} : HTTP {response.status_code} {response.text[:200]}")
    return response.json()


async def session_status() -> dict:
    """Vérité terrain avant d'écrire : `authenticated` dit si le panier appartient au compte."""
    return await _call("GET", "/health")


async def search(query: str, limit: int = 10) -> list[Offer]:
    """Le nom nu de l'aliment → les offres du drive. Un échec lève, il ne rend pas []."""
    data = await _call("POST", "/search", {"query": query, "limit": limit})
    return [
        Offer(
            name=str(item.get("name") or ""),
            product_id=str(item.get("product_id") or ""),
            offer_id=str(item.get("offer_id") or ""),
            drive_a_id=item.get("drive_a_id"),
            brand=item.get("brand"),
            seller_id=item.get("seller_id"),
            stock=int(item.get("stock") or 0),
        )
        for item in data.get("results", [])
    ]


async def get_cart() -> dict:
    return await _call("GET", "/cart")


async def pin_cart(cart_id: str) -> dict:
    """Épingler le panier avant la première écriture — le self-heal le détache sinon."""
    return await _call("POST", "/cart/id", {"cart_id": cart_id})


async def add_to_cart(offer: Offer, quantity: int = 1) -> dict:
    return await _call("POST", "/cart/items", {
        "product_id": offer.product_id,
        "offer_id": offer.offer_id,
        "quantity": quantity,
        "seller_id": offer.seller_id,
    })


async def set_quantity(offer: Offer, quantity: int) -> dict:
    """Fixe la quantité portée par le drive pour cette offre ; 0 retire la ligne."""
    return await _call("POST", "/cart/items/remove", {
        "product_id": offer.product_id,
        "offer_id": offer.offer_id,
        "quantity": quantity,
        "seller_id": offer.seller_id,
    })


def push_target(before: int, quantity: int) -> int:
    """`POST /cart/items` REMPLACE la quantité d'un produit déjà au panier : on pose donc le total (#175)."""
    return before + quantity


def push_error(before: int, target: int, after: int) -> str | None:
    """Le motif d'un ajout que la relecture dément, None s'il a bien eu lieu."""
    if after == target:
        return None
    if after <= before:
        return f"l'ajout n'a rien changé au panier ({before} exemplaire(s) avant comme après)"
    return f"le drive porte {after} exemplaire(s) au lieu de {target} : quantité plafonnée"


def edit_target(in_cart: int, line_quantity: int, wanted: int) -> int:
    """Ce que le drive doit porter, sans toucher aux exemplaires qu'une autre ligne a posés sur la même offre."""
    return max(0, in_cart - line_quantity + wanted)


def cart_lines(cart: dict) -> list[dict]:
    """Les lignes d'un panier, quel que soit le nom que leur donne le drive."""
    for key in ("lines", "items", "products"):
        value = cart.get(key)
        if isinstance(value, list):
            return value
    return []


def count_for(cart: dict, offer: Offer) -> int:
    """Combien d'exemplaires de cette offre le drive dit porter — 0 si aucune ligne."""
    wanted = {offer.offer_id, offer.product_id, offer.drive_a_id} - {None, ""}
    for line in cart_lines(cart):
        refs = {str(line.get(k)) for k in
                ("offer_id", "offerId", "product_id", "productId", "drive_a_id")}
        if refs & wanted:
            return int(line.get("quantity") or line.get("qty") or 0)
    return 0


async def create_order() -> dict:
    """Convertit le panier en commande. Une erreur du checkout lève, elle ne rend rien."""
    return await _call("POST", "/order")

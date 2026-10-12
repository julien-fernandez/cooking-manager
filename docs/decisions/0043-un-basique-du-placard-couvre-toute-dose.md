# 0043 — Un basique du placard couvre toute dose

- **Statut** : accepté
- **Date** : 2026-10-06
- **Concerne** : `food.pantry_staple`, `cooking_manager/pantry.py`, `cooking_manager/ingredient_map.py`,
  `GET /api/menus/{slug}/shopping-list`, `GET /api/menus/{slug}/ingredient-map`, `PUT /api/pantry/staples/{food_key}`
- **Résout** : le fond de cuisine (#187, discussion du 06/10) · **Amende** : ADR 0036 · **Voisin** : ADR 0042

## Contexte

Épices, huiles, condiments, pâtisserie et bouillons se gardent en pots dont on prélève une cuillère.
L'ADR 0036 refusait un `ok` sans quantité : 50 lignes sur 66 de ces rayons n'en avaient pas, rendaient
`inconnu` face aux recettes, et le tour de confirmation les redemandait chaque semaine.

## Décision

Un aliment `pantry_staple` est un **basique du placard**. Face à un besoin :

| Garde-manger | Verdict | Achat |
|---|---|---|
| une ligne `ok`/`low`, avec ou sans quantité | `placard` « au placard » | non |
| toutes les lignes `out` | `absent` | oui |
| aucune ligne | `placard`, `declared: false` | non, compté dans `staples_undeclared` |

Au-delà de **300 g ou 300 ml** pour le besoin consolidé, le basique est mesuré comme un aliment
ordinaire, et le motif le dit. Un besoin sans `food_key` qui ressemble à un basique ressort dans
`staples_unlinked`. Les deux compteurs se lisent **avant** `lines` et `recipes`.

**Amendements à l'ADR 0036** : un basique peut être `ok` sans quantité ; il ne figure pas au tour de
confirmation du garde-manger.

## Conséquences

- `counts.placard` se lit à part de `counts.suffisant` : couvert parce que basique n'est pas mesuré.
- Les basiques au kilo (farine, sucre, riz, pâtes) ne reçoivent jamais `pantry_staple`.
- Un basique ne s'achète que déclaré fini (`PUT /api/pantry/staples/{food_key}` `{"status": "out"}`, livrée avec les écrans ; d'ici là, une ligne `out` par `PATCH /api/pantry`).

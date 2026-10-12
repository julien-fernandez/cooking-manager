# 0042 — Une élection ne survit pas à ses entrées

- **Statut** : accepté
- **Date** : 2026-10-05
- **Concerne** : `cooking_manager/cart_freshness.py`, `cooking_manager/pantry.py`,
  `cooking_manager/verification.py`, `POST /api/shopping/validate-cart`, `POST /api/cart/items`,
  `GET /api/cart`, `POST /api/menus`, `menu.meals_changed_at`
- **Résout** : #186, #187 · **Étend** : ADR 0039 · **Voisin** : ADR 0036, 0038

## Contexte

Une ligne de `cart_item` est élue d'après trois entrées : les repas du menu, le stock
confirmé, la quantité nécessaire. Aucune ne la figeait. Les courgettes l'ont montré : le menu
réécrit, la ligne élue restait au panier ; un besoin en pièces et en grammes se lisait comme
deux besoins ; un stock en grammes face à un besoin en pièces rendait `inconnu`, et la ligne
s'achetait quand même. `validate-cart` laissait partir un panier dont plus rien ne justifiait
les lignes.

## Décision

**Une ligne `menu` ou `substitution` (`elected`, `asked`) est périmée dès que l'une de ses
entrées bouge.** `validate-cart` rend `stale` et `counts.stale`, et `ok:false`, pour :

| Cause | Quand |
|---|---|
| `food_gone` | l'aliment n'est plus dans le menu — seulement si le menu a des `food_key` liés, sinon c'est inconnu et cette cause ne s'applique pas |
| `menu_rewritten` | élue avant `menu.meals_changed_at` — déplacé seulement si `meals` change réellement, ou si un `PATCH` d'un repas change `recipe_slug`, `dish` ou `covers` ; NULL pour un menu d'avant la migration |
| `pantry_confirmed` | élue avant `pantry_confirmation.updated_at` |

`GET /api/cart` porte `stale` sur chaque ligne et `counts.stale`. Une **ré-élection** du même
`food_key` ET du même nom demandé (`normalize_name`) marque les anciennes lignes
`menu`/`substitution` `skipped` (« remplacée par la ligne N — ») : un aliment peut avoir
plusieurs lignes de courses (`ail` en gousses et en g), la seconde n'annule pas la première.
Une ligne périmée dont le stock couvre désormais le besoin sort sans achat : un `POST` d'origine
`menu` dont la ligne de courses (par `food_key`, sinon par nom) dit que le stock suffit
(`outcome: suffisant`, non supposé épuisé ; `purchase` n'est pas vide pour autant) n'écrit
aucune ligne, marque `skipped` les lignes ouvertes de ce `food_key` et de ce nom
(« couvert par le stock — ») et rend `{"verdict": "covered", "skipped": [ids], "reason"}`.
Sans ligne de courses trouvée, le comportement reste celui d'avant.
`POST /api/menus` marque `skipped` les lignes `food_gone`, avec la même règle que `validate-cart`
(`stale_lines` : un menu sans `food_key` lié ne dit rien du départ d'un aliment).

**Un stock incomparable se demande, il ne s'achète pas.** Un `POST /api/cart/items` d'origine
`menu` dont la ligne de courses est `inconnu` (stock présent, unités sans conversion) écrit
`status: asked` avec la question (« tu en as assez ? »), sans élection au drive, même avec un
produit nommé. La réponse passe par `PATCH /api/pantry` avec une quantité mesurable, puis une
nouvelle élection.

**Le besoin d'un aliment tient dans une unité.** Pour un aliment qui a un poids typique
(`TYPICAL_PIECE_GRAMS`), pièces et grammes se fusionnent en un besoin
en g au poids typique (`estimate` sur la ligne, « poids estimé » dans `reason`). Le stock dans
une autre unité est converti (pièce↔g, tête↔gousse ; « tête » devient une unité reconnue), avec
« poids estimé » ou « équivalent estimé ». Des unités identiques non-base se comparent telles
quelles. Sans conversion, `inconnu` reste `inconnu`.

**`verify` juge le surplus sans contenant.** Il somme les lignes pièce + g du panier en g au
poids typique. Sans contenant connu, il rend SURPLUS quand l'excédent dépasse 25 % du besoin
(`SURPLUS_RATIO_UNKNOWN_PACK`), en g/ml seulement. SURPLUS ne bloque pas. Une ligne illisible
rend l'aliment `non_mesurable`.

## Conséquences

- Sans contenant connu, acheter le plus petit produit vendu (sel 1 kg pour 100 g) se lit
  SURPLUS (non bloquant) : du bruit attendu.
- `counts.stale` se lit **avant** `lines` : des lignes présentes mais périmées donnent un panier
  qui se croit à jour.
- `Pantry.find` apparie par `food_key` d'abord, avant l'alias et le nom ; une ligne substituée
  par régime n'a pas de `food_key` (`parts.apply_repairs` pose `"food_key": None`). Un appariement par `food_key` **prime donc sur un
  `pantry_alias` explicite**.
- Les poids typiques sont des estimations : jamais présentés comme un poids lu, toujours dits
  dans `reason`.
- Un menu d'avant la migration (`meals_changed_at` NULL) ne périme rien par réécriture : seules
  `food_gone` et `pantry_confirmed` le frappent.

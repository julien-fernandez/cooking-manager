# 0044 — Un gate est un quantificateur recalculé, le journal est en ajout seul

- **Statut** : accepté
- **Date** : 2026-10-07
- **Concerne** : `cooking_manager/gates.py`, `backend/gates.py`, table `gate_verdict` (`backend/db.py`),
  `GET /api/menus/{slug}/gates`, `PATCH /api/menus/{slug}`, `POST /api/cart/items`, `POST /api/cart/push`,
  `POST /api/cart/order`, `POST /api/cart/verify`
- **Résout** : les six trous du 05/10 (gates décoratifs) · **Voisin** : ADR 0036, 0042, 0043 ·
  **Spec** : `docs/superpowers/specs/2026-10-07-moteur-de-gates-design.md`

## Contexte

L'avancement de la semaine vivait en prose de skill : aucune route de transition ne vérifiait le gate
de l'étape d'avant (sauf la session Drive A au `push`). Un silence se lisait comme un feu vert. Le 05/10,
six trous en sont sortis : un garde-manger jamais revu (miel), une ligne `asked` poussée (pain complet),
un `verify` en MANQUE commandé quand même (persil)... Des gates qui ne bloquent rien sont décoratifs.

## Décision

Un gate est un **quantificateur calculé depuis la base**, déclaré dans un **registre pur**
(`cooking_manager/gates.py`) : `id`, étape, seuil, et une fonction `measure()` sans I/O. Le seuil ne
s'écrit que là. Les loaders (`backend/gates.py`) lisent la base.

Quatre états : `mesuré_ok`, `mesuré_ko`, `non_mesuré`, `pas_câblé`. Un loader ou un `measure()` qui lève
rend `non_mesuré`, jamais vert. `pas_câblé` (gate déclaré, spec à venir) est visible, jamais vert, et ne
bloque pas.

`GET /api/menus/{slug}/gates` **recalcule tout à chaque appel** et n'écrit jamais dans le journal. L'iPad
et l'agent lisent la même fonction (`evaluate`), qui produit aussi la décision du 409.

Quatre transitions rendent **409** tant qu'un gate exigé est `mesuré_ko` ou `non_mesuré`, selon une règle
cumulative déduite du numéro d'étape :

| Transition | Route | Étapes exigées |
|---|---|---|
| `publish` | `PATCH /api/menus/{slug}` `status=active` | 1 · 2 · 3 · 4 |
| `elect` | `POST /api/cart/items`, origine `menu` ou `substitution` | 1 · 2 · 3 · 4 · 6 |
| `push` | `POST /api/cart/push` | 1 · 2 · 3 · 4 · 6 · 7a · 8 |
| `order` | `POST /api/cart/order` | 1 · 2 · 3 · 4 · 6 · 7a · 8 · 9 |

Forcer = un `override_reason` non vide (des espaces comptent pour absent), dit à Julien. L'étape s'affiche
alors `forcé`, jamais `vert`. L'acteur vaut `agent` ou `ipad`, sinon 422.

**Journal `gate_verdict`, en ajout seul** : jamais d'`UPDATE` ni de `DELETE`. Une ligne par gate exigé à
chaque tentative de transition (`passé`, `refusé`, `forcé`), une ligne `verify_missing` à chaque `verify`
(`mesuré`). Table dans `SCHEMA_SQL` et `MIGRATIONS_SQL`, index dans la migration seule.

**Gate 9 mesuré au `verify`**, journalisé avec l'**empreinte** des lignes vivantes du panier. `/gates`
relit la dernière ligne : aucun verify ou empreinte différente → `non_mesuré`.

## Écarts assumés par rapport à la spec

- **Loaders = handlers existants appelés en Python**, pas une extraction de `menu_shopping_list`. Le
  risque d'un champ renommé est couvert : chaque `measure()` lit les clés en accès strict
  (`payload["clé"]`), un `KeyError` rend `non_mesuré`.
- **`order` mesure le gate 9 à neuf avant de juger** : la route relit le panier, journalise ce verdict
  (`record_verify`), puis `require_gates("order")` le relit. Pour cette seule route, `require_gates`
  passe après la lecture du panier.
- **`published`** = menu `active` ∧ un seul menu actif (« repas = créneaux » est déjà le gate 2).
- **`food_pending`** ne regarde que l'étage `food_key` (`name_normalized` d'une ligne de courses) ;
  l'étage `food_kind` n'a pas de clé sur une ligne de courses et reste hors gate.
- **Une confirmation aveugle du garde-manger garde le gate 6 rouge** : « aucune ligne regardée » est
  précisément le trou du miel. On passe par `override_reason`.
- **Les routes productrices restent libres** (`pantry-confirm`, arbitrage, `served`, `PATCH` d'un repas,
  `verify`, `child-week/sync`) : les bloquer empêcherait de réparer un gate rouge.
- **`elect` garde les origines `menu` et `substitution`** (une substitution élit un besoin du menu) ; récurrent et manuel restent gardés par `push`.
- **La bande iPad compte 14 pastilles**, une par étape.
- **Le corps du 409 est sous `detail`** (enveloppe FastAPI de `HTTPException`).
- **`passé` au journal dit « a passé les gates »** : la route peut encore échouer ensuite (session
  Drive A morte, drive injoignable).
- **Un acteur invalide rend 422** dès le modèle (`Literal["agent", "ipad"]`) et dans `record_verify`.
- **`POST /api/menus` ne publie pas** : `status: active` sur un menu qui n'est pas déjà actif rend 409
  (publier par `PATCH`, qui passe par les gates) ; réécrire un menu déjà actif reste permis.
- **Le gate 9 est `non_mesuré` si des besoins n'ont pas d'aliment** (`food_link.unlinked > 0`) : ils ne
  sont pas confrontés au panier, un zéro MANQUE ne prouve rien.
- **Un forçage ne s'attribue qu'à un gate alors `mesuré_ko` ou `non_mesuré`** : un `forcé` écrit pour un
  gate vert ne revient pas hanter l'étape plus tard.
- **Une étape non câblée (5, 7b, 7c) rejoindra les exigences de sa transition** une fois câblée :
  la carte se déduit du registre.
- **Fenêtre « à partir d'aujourd'hui » pour les gates 1 à 4** (décision de Julien, en attendant la spec 04,
  passé = mangé) : `load_inputs` passe la date du jour à `menu_shopping_list` et `menu_compatibility`
  (`from_date`), et ne garde que les jours >= aujourd'hui pour le gate 1. Les sources des restes ne sont
  pas filtrées. `GET /gates` dit la fenêtre dans `window`.

## Conséquences

- `pas_câblé` est visible et non bloquant (5, 7b, 7c, 8.5, 10) ; chaque spec suivante bascule son gate
  en mesuré.
- Un gate câblé exige un cas connu-faux et un cas connu-vrai qui rendent des états différents ; un
  méta-test du registre l'impose, ainsi que la règle cumulative.
- Un 409 de gate est un arrêt, pas un obstacle : on corrige la donnée, on ne force qu'avec un motif dit
  à Julien.
- Le journal grossit sans purge ; c'est le prix d'un refus qui persiste sur le disque.
- Limite dite franchement : la Danette (#203) est un mauvais appariement, pas un sujet `pending` ;
  `food_pending` ne la voit pas.

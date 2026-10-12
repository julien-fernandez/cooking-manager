---
numero: 0041
titre: Une part vaut une portion, et les restes s'achètent avec leur plat
statut: accepté
date: 2026-10-05
concerne:
  - cooking_manager/parts.py
  - backend/app.py
---

# 0041 — Une part vaut une portion, et les restes s'achètent avec leur plat

## Contexte

Retours de Julien sur le menu du 05/10 : « le mafé avec 300 g pour Claire, c'est trop » et
« le mafé est vu à 10 portions, pourquoi ? ». Deux causes, mesurées sur
`GET /api/menus/{slug}/shopping-list` :

- Le mafé est une recette de **10 portions**. Sa part `for_person_id = Claire` (300 g de
  crevettes) était multipliée par `tablée / servings` comme une ligne commune : la fiche disait
  300 g, la liste achetait 120 g, et aucun des deux chiffres n'était une portion. ADR 0037 avait
  dit **pour qui** est une part, jamais **combien** elle pèse.
- Le jeudi midi portait « Restes du mafé » pour Claire. La liste écartait le repas `leftovers`
  (pas de fiche) **sans ajouter ses mangeurs au plat source** : les restes n'étaient jamais
  achetés. Et la ligne de poulet que la part remplace était achetée pour Claire aussi.

## Décision

`portions()` ramène chaque ligne d'une fiche à ses **mangeurs** avant `build_needs` :

- **Une ligne `for_person_id` vaut UNE portion pour cette personne, par repas où elle mange le
  plat** — indépendante de `servings`. Personne absente : la part ne s'achète pas.
- **Une ligne commune** suit `portions / servings`, moins les portions de ceux dont la part la
  remplace (`replaces_position`).
- **Un reste ajoute sa tablée à celle du plat source** (`eaters_by_meal`, via
  `menu_meal.leftovers_of`). Claire qui mange ses restes le lendemain compte deux portions de
  sa part.

Des couverts imposés (`menu_meal.covers`, `?covers=`) priment toujours sur la tablée ; les restes
s'y ajoutent. Un repas sans date garde l'ancien ratio : sa tablée est inconnue, et on ne retire
pas une part sur une ignorance.

## Conséquences

- Une part s'écrit **pour une personne** : 120–150 g de poisson ou de crevettes crus, un pavé.
  Mesuré le 2026-10-05 : 9 des 11 parts en base l'étaient déjà ; le mafé (300 g) a été ramené à
  120 g. `salade-vietnamienne` (1 kg de concombre, recette retirée) reste à reprendre.
- Un reste sans source exploitable (`leftovers_of` NULL, #76) n'est toujours ni contrôlé ni
  acheté : le lier reste le geste de composition.
- `/nutrition` et `/macros` ne passent pas par `portions()` : leur `per_portion` reste celui de
  la fiche.

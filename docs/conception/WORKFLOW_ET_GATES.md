---
title: Workflow de la semaine et gates — conception générale
axis: architecture
proof_level: provisional
upstream: [USE_CASES_COURSES.md, ../../CLAUDE.md, julien-cooking-manager-weekly-prep]
downstream: [spec 01 moteur de gates, spec 02 tour+canal, spec 03 produit+réception, spec 04 passé=mangé, spec 05 session durable, spec 06 non-alimentaire]
status: draft
date: 2026-10-07
---

# Workflow de la semaine et gates — le 00-general de la refonte

> Session de brainstorm du 2026-10-07 (skill `superpowers:brainstorming`).
> But : retravailler **tout** le workflow menu → liste → garde-manger → drive →
> réception → cuisine pour décider **où placer les points de vérification (gates)**,
> en s'inspirant de « 2026.09 Audioguides - refacto » (`docs/brainstorm/00-general.md`,
> gates quantificateurs) et de « 2026.01 Job search 2026 » (audit `--ci` + `--demo`
> à chaque rendu).
> Les sessions suivantes partent de ce document (voir § Roadmap). Ce document
> **ne touche pas aux recettes** : c'est la session 2, après consolidation.

## 1. Le problème — six trous, chacun à une étape différente

La semaine du 2026-10-05 a eu six manques (jeu → dim), alors que l'agent avait fait
le menu **et** le drive le lundi. Chaque manque vient d'une **étape différente** du
workflow, et chaque fois un silence s'est lu comme un feu vert :

| Manque | Étape fautive | Cause |
|---|---|---|
| Crème | liste (appariement) | « Danette crème dessert » couvrait la crème (#203, corrigé) |
| Piment d'Espelette | liste (appariement) | « Cassegrain poivrons au piment d'Espelette » couvrait le piment (#203) |
| Miel | garde-manger | 3 pots `ok` en base, finis en réalité ; le drive est parti **avant** la revue |
| Pain complet | panier | élu, retiré « menu révisé », **jamais ré-élu** ; pain de mie sauté (ban) |
| Pulpe de tomate | réception | `pushed` 2×400 g, **absente de la commande reçue** — rien ne confronte |
| Persil plat | panier | « persil » acheté en **frisé** (fusion par nom, #166) |

Et une erreur d'agent : la liste calculée sur **toute la semaine** (repas déjà mangés
compris, `served` jamais posé) face au stock du jour → faux manques.

**Racine commune** (la même qu'Audioguides) : le pipeline vit en **prose de skill**
interprétée par le LLM ; la vérité — état d'un tour, verdicts, décisions
d'approvisionnement — n'habite aucune structure que du code refuse. Deux gates
« décoratifs » vérifiés cette session le confirment :

- Le ping uptime d'`drive_a-orders` rend « OK » pendant que le scrape meurt sur session
  anonyme (le scrape n'a rien rapporté, le healthcheck était vert).
- `cookiectl relogin` déclare « already-authenticated » pendant que `heal` déclare
  « SessionDead » sur la même session : deux outils, deux vérités, aucun quantificateur.

## 2. Les principes de construction

1. **Un gate = un quantificateur.** Un nombre calculé depuis la base (ratio, comptage),
   jamais un booléen déclaré ni un `exit 0`. Le seuil s'écrit à **un seul endroit** : le
   code qui le mesure.
2. **Trois états partout** : mesuré-OK · mesuré-KO · **non-mesuré**. Un signal absent
   n'est jamais vert. C'est déjà la discipline des ⛔ du CLAUDE.md : lire le compteur
   « non-mesuré » (`preferences_unmeasurable`, `conflicts_uncovered`, `slots_uncomposed`,
   `pantry.confirmation.blind`, `pack_known`, `cart_unreadable`…) **avant** son voisin
   rassurant.
3. **Un gate est lu des deux côtés, par la même route.** `GET /api/menus/{slug}/gates`
   recalcule tout depuis la base à chaque appel ; l'agent reçoit **409 à la transition**
   quand le gate de l'étape n'est pas vert ; l'iPad affiche le même verdict. Rien n'est
   stocké, donc rien ne peut mentir sur l'avancement : « où en est la semaine » = la
   dernière étape dont tous les gates sont verts.
4. **Toute décision atteint le disque, et se rejoue.** Source d'un aliment, produit
   préféré, arbitrage : en base, avec **motif** et **provenance** (« déclaré » vs
   « appris »). Jamais « de mémoire ». Une décision rendue ne se redemande pas.
5. **Producteur ≠ juge.** L'étape qui compose ne valide pas sa propre compat ; l'appli
   qui élit ne se croit pas sur parole (le panier est une table, ADR 0039).
6. **La mort est bruyante.** Une dépendance qui tombe (session Drive A) **alerte** ; elle
   ne rend pas « OK ». Un verdict rouge persiste sur le disque, jamais silencieux.
7. **Chaque gate porte un cas connu-faux ET un connu-vrai** (discipline Job search) :
   s'ils rendent la même chose, l'instrument n'a rien mesuré. Les six trous du § 1 sont
   les cas connus-faux de départ.

## 3. La colonne vertébrale — étape, gate, mémoire, trou attrapé

Chaque étape ne débloque la suivante que si son gate rend un quantificateur vert.

| # | Étape | Gate de sortie | Mémoire (lue/écrite) | Trou attrapé |
|---|---|---|---|---|
| 1 | Tablée | `jours_non_résolus = 0` | child_week, attendance | — |
| 2 | Repas composés | `créneaux_à_table_sans_plat = 0` | menu_meal | — |
| 3 | Fiches reliées | `repas_orphelins = 0` | — | — |
| 4 | Compat & préférences | `conflits_non_couverts = 0` ∧ `parts_non_mentionnées = 0` | person, parts | — |
| 5 | **Fenêtre de calcul** (le *tour* se fige) | `repas_passés_non_tranchés = 0` (passé = mangé, stock décompté) | menu_meal.served, stock estimé | faux manques |
| 6 | Garde-manger confronté | `lignes_aveugles = 0` (revue **datée de ce tour**) | pantry_confirmation | miel |
| 7a | Aliment du besoin | `besoins_sans_aliment = 0` (hors NON_PURCHASE) | arbitrage `food_key`/`food_kind` | crème, piment (#203) |
| 7b | Canal (par type) | `lignes_non_attribuées = 0` à la clôture | `shopping_preference(channel)` | *(pain → boulangerie)* |
| 7c | Produit (si drive) | `besoins_drive_sans_produit_ni_question = 0` | **`shopping_preference(product)` NEW** + cart_item | pain complet (jamais ré-élu) |
| 7d | Contenant | `pack_known` lu avant `packs` (ADR 0038) | packing | — |
| 8 | Panier posé (drive) | `asked = 0` ∧ `périmées = 0` (ADR 0042) | cart_item | — |
| 8.5 | **Créneau réservé** | `créneau_réservé ∧ maintenant < heure_limite` | créneau drive | menu prêt, courses qui n'arrivent pas |
| 9 | Commande prouvée (drive) | `verify.MANQUE = 0` ∧ `authenticated` | shopping_session | persil (frisé ≠ plat) |
| 10 | **Réception — deux formes** | drive : `commandé − livré = 0 ou expliqué` · manuel : lignes **cochées** | pantry (info dégradée **visible**) | pulpe |
| 11 | Publié iPad | `menus_actifs = 1` ∧ `repas = créneaux` | menu.status | iPad resté sur l'ancienne semaine (#71) |

**Gates transverses** (veillent en continu, pas une étape) :
- **Session Drive A** : `authenticated = true` — bruyant quand il tombe + warm PC→VPS
  durable (§ 6).
- **Vérité mesurée** : aucun compteur rassurant lu avant son « non-mesuré » voisin.

## 4. Le modèle « tour multi-canal » — l'ossature de la moitié courses

Prolonge `USE_CASES_COURSES.md` (2026-08-16), déjà tranché avec Julien et resté non câblé.

- **La liste n'est pas un objet, c'est le résidu d'un calcul.** L'unité est le **tour** :
  une sortie, un canal, un moment (drive lundi, marché samedi, boucher jeudi).
- **Un tour ouvert réserve ses lignes et se fige.** Si une recette change après, il **ne
  se réécrit pas tout seul** : il signale l'écart (c'est déjà l'ADR 0042 pour le drive).
- **Attribution d'une ligne à un canal, trois sources hiérarchisées** (jamais
  d'estimation implicite) : (1) réattribution ponctuelle (le tour seul) > (2) mémoire
  d'habitude `shopping_preference(pref_type='channel')` > (3) défaut par rayon > sinon
  **`non attribué`** — visible, **bloquant à la clôture du tour**. La réattribution
  **n'écrase jamais** la mémoire.
- **Le canal n'est pas une étiquette** : le drive a un catalogue interrogeable, des
  quantités exactes et une facture ; boucher / marché / boulangerie n'ont pas de
  catalogue, se cochent à la main, et le garde-manger qui en vient est **structurellement
  moins précis — ça doit se voir, jamais se deviner**. → la réception (étape 10) a donc
  **deux formes** selon le canal.

## 5. Décidé déjà vs vraiment nouveau

Le spec s'appuie sur les ADR ; on ne réinvente pas un mécanisme qui existe.

**Déjà tranché :**
- tour figé qui réserve ses lignes — `USE_CASES_COURSES.md` + ADR 0042 ;
- canal = `shopping_preference(pref_type='channel')`, hiérarchie à 3 sources,
  `non attribué` bloquant, réattribution qui n'écrase pas — `USE_CASES_COURSES.md` ;
- canal ≠ étiquette, info dégradée visible — idem ;
- arbitrage à deux étages (aliment exact + famille), `settled`/`pending`/`decided_by`,
  un arbitrage rendu ne se redemande pas — ADR 0032, 0035 ;
- élection bornée `elected`/`substitution`/`ask`, motif toujours porté — ADR 0039 ;
- péremption d'une élection (`stale`, ré-élection → ancienne `skipped`) — ADR 0042 ;
- contenant (plus petit connu gagne, `pack_known`) — ADR 0038 ;
- garde-manger quantifié à l'entrée, confirmé avant le panier — ADR 0036 ;
- substitution recette (protéine → poisson selon contexte, régime), motif porté — ADR 0001.

**Vraiment nouveau (aucune décision) :**
- **produit préféré durable** parmi plusieurs candidats → `shopping_preference(pref_type='product')`
  (clé = aliment, valeur = `offer_id` + motif + provenance « déclaré »/« appris »). Même
  table que le canal et le récurrent : une seule mémoire de courses, cohérente ;
- **passé = mangé par défaut**, et **stock décompté** (le garde-manger devient un
  inventaire **estimé** : entrées − repas mangés, marqué « estimé » jusqu'à la prochaine
  revue qui le remet à la mesure) ;
- **réception à deux formes** (drive relu vs cochage manuel) avec gate d'écart ;
- **les gates eux-mêmes** : recalcul, 409 aux transitions, journal `gate_verdict`, route
  `/gates` ;
- **session Drive A bruyante** + warm PC→VPS durable ;
- **le créneau** comme étape gardée (8.5) ;
- **le non-alimentaire** (PQ, dentifrice, ménager) — trou connu, spec 06, plus tard.

## 6. Décisions de cette session (2026-10-07)

| # | Question | Décision |
|---|---|---|
| D1 | Qui les gates arrêtent-ils ? | **Les deux** (agent + iPad), **un même mécanisme** : route `/gates`, 409 pour l'agent, affichage pour l'iPad. |
| D2 | Où placer la revue du garde-manger ? | **Quand on le demande + avant le panier.** Le gate 6 n'impose pas une revue en tête de semaine, mais exige qu'une revue **datée de ce tour** existe avant l'élection (étape 7). |
| D3 | Réception, qu'est-ce qui fait foi ? | **Drive A relu, puis Julien sur l'écart.** On relit la commande livrée (ruptures, substitutions) ; l'iPad montre l'écart commandé − livré ; le stock n'est écrit qu'après. |
| D4 | Repas passé non marqué ? | **Mangé par défaut**, stock consommé, sort de la liste. Julien ne marque que l'exception. Le gate affiche combien de repas sont supposés, jamais en silence. |
| D5 | Un repas mangé décrémente-t-il le stock ? | **Oui, décompté** (inventaire estimé, remis à la mesure à la revue). |
| D6 | Granularité de la décision de source | **Deux niveaux comme l'arbitrage** : par famille (`food_kind`) ET par aliment précis (`food_key`) ; l'aliment précis l'emporte. |
| D7 | Granularité du canal (axe laissé ouvert par le doc du 16/08) | **Par type** (« un drive », « la boucherie »), pas par enseigne. Si un jour deux drives, on raffinera. |
| D8 | Apprentissage d'une habitude de canal (seuil D.19) | **Déclarée seulement**, pour l'instant. Pas d'apprentissage auto ; on garde la provenance « déclaré » vs « appris » pour plus tard. |
| D9 | Portée du modèle tour multi-canal | **Multi-canal, par étapes** : le modèle tour/canal est l'ossature, construit par jalons (canal + source mémorisée + réception à deux formes d'abord). |
| D10 | Produit préféré, où le ranger ? | `shopping_preference(pref_type='product')` — pas une table parallèle, pas l'arbitrage (qui reste pour l'**identité** d'un aliment). |
| D11 | Non-alimentaire | **Oui, mais plus tard** (spec 06). Trou connu porté dans la carte. |
| D12 | Créneau drive + heure limite | **Oui, étape + gate** (8.5), entre panier posé et commandé. |
| — | Équipement de cuisine (contrainte AppRef) | **Hors périmètre** (cuisine fixe). |

## 7. Comparaison AppRef — ce qu'elle a confirmé

Le flux grand public de AppRef, mis en regard de la carte, a confirmé la couverture et
révélé trois oublis :

1. **Non-alimentaire / produits du quotidien** — AppRef en fait une catégorie de première
   classe ; notre workflow est 100 % piloté par le menu. → D11, spec 06.
2. **Créneau + heure limite** — vraie étape avec deadline dure. → D12, étape 8.5.
3. **Équipement de cuisine** — AppRef filtre les recettes dessus. → hors périmètre.

Couverts par AppRef et déjà chez nous : parts par recette (ADR 0041), cocher le placard
(`pantry-confirm`), substitutions de rupture (ADR 0039), fiche + photo sur l'iPad.

## 8. Roadmap des sessions-spec (l'ordre de construction ≠ l'ordre des étapes)

Protocole inter-sessions : **le fichier est le canal.** Chaque session lit ce document
et les specs précédentes, produit la sienne, s'arrête. Le modèle de données et le moteur
de gates d'abord ; les étapes s'y adossent.

| Spec | Sujet | Dépend de |
|---|---|---|
| **00** (ce document) | la carte : étapes, gates, principes, mémoires, décidé/nouveau, décisions | — |
| 01 | **moteur de gates** : recalcul depuis la base, 409 aux transitions, journal `gate_verdict`, route `GET /api/menus/{slug}/gates`, chaque gate avec son connu-faux + connu-vrai | 00 |
| 02 | **tour + canal** (par type) + source mémorisée `shopping_preference(channel)` + `non attribué` bloquant à la clôture | 00, 01 |
| 03 | **produit préféré durable** `shopping_preference(product)` + **réception à deux formes** (drive relu / cochage manuel) avec gate d'écart | 00, 01, 02 |
| 04 | **passé = mangé** + **stock décompté estimé** + fenêtre de calcul (le tour se fige) | 00, 01 |
| 05 | **session Drive A bruyante** + **warm PC→VPS durable** (réactiver la propagation drive_a.fr côté PC, retirée le 2026-08-12 ; rendre la mort bruyante) | 00 (indépendant) |
| 06 | **non-alimentaire** (PQ, dentifrice, ménager) comme habitude de courses non liée au menu | 00, 02 |
| — | **recettes** (session 2 de Julien) — méthodologie propre, après consolidation | 00–06 |

Chaque session applique la méthode `superpowers:brainstorming` (questions une par une →
approches → design par sections → spec écrite et relue).

## 9. Les six trous comme cas de test

Chaque gate naît avec son cas connu-faux (le trou) et son connu-vrai :

| Gate | Cas connu-faux (doit refuser) | Cas connu-vrai (doit passer) |
|---|---|---|
| 6 garde-manger | miel `ok` jamais regardé ce tour → `lignes_aveugles > 0` | revue datée de ce tour, tout vu |
| 7a aliment | « Danette » couvrant « crème » (#203) → besoin sans aliment réel | aliment exact rattaché |
| 7c produit | pain complet retiré, jamais ré-élu → besoin sans ligne vivante | ligne élue ou motif écrit |
| 5 fenêtre | liste sur toute la semaine, `served` jamais posé → repas passés non tranchés | passé = mangé, stock décompté |
| 10 réception | pulpe `pushed` mais absente du reçu → écart non expliqué | écart = 0 ou motif |
| 9 commande | persil frisé pour persil plat (fusion par nom) → MANQUE sur le besoin | produit du bon aliment |

Tant qu'un gate rend la même chose sur son connu-faux et son connu-vrai, il n'a rien
mesuré — on ne le câble pas.

-- Une ligne de recette qui nomme plusieurs aliments n'en porte qu'un : on la scinde (ADR 0043, validé par Julien le 06/10).
-- Sans scission, « poivre et beurre » s'absorbe dans le besoin « poivre » et le beurre n'est plus confronté au stock.
-- Aucune ligne visée ne porte de part de convive (#167). À lancer AVANT `staples_backfill.py apply`. Rejouable : rien ne
-- correspond plus après le premier passage.
BEGIN;

CREATE TEMP TABLE split (src TEXT, keep_name TEXT, keep_food TEXT, extras TEXT[]) ON COMMIT DROP;
INSERT INTO split VALUES
    ('sel poivre', 'sel', NULL, ARRAY['poivre']),
    ('sel et poivre', 'sel', NULL, ARRAY['poivre']),
    ('poivre et beurre', 'beurre', 'beurre', ARRAY['poivre']),
    ('sel jus de citron', 'jus de citron', 'citron', ARRAY['sel']),
    ('huile d olive sel muscade cumin', 'huile d olive', 'huile olive', ARRAY['sel', 'muscade', 'cumin']);

INSERT INTO recipe_ingredient (recipe_id, position, raw, name, name_normalized, is_optional, parsed)
SELECT ri.recipe_id,
       (SELECT max(x.position) FROM recipe_ingredient x WHERE x.recipe_id = ri.recipe_id)
           + row_number() OVER (PARTITION BY ri.recipe_id ORDER BY ri.position, e.ord),
       e.name, e.name, e.name, ri.is_optional, ri.parsed
  FROM recipe_ingredient ri
  JOIN split s ON s.src = ri.name_normalized
 CROSS JOIN LATERAL unnest(s.extras) WITH ORDINALITY AS e(name, ord)
 WHERE ri.for_person_id IS NULL;

UPDATE recipe_ingredient ri
   SET raw = s.keep_name, name = s.keep_name, name_normalized = s.keep_name,
       food_key = COALESCE(s.keep_food, ri.food_key)
  FROM split s
 WHERE s.src = ri.name_normalized AND ri.for_person_id IS NULL;

COMMIT;

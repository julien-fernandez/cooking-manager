"""food.pantry_staple : la colonne existe des deux côtés du schéma et l'API la lit et l'écrit (ADR 0043)."""

import inspect

from backend import app as app_module
from backend import db


def test_colonne_dans_le_schema_et_la_migration():
    assert "pantry_staple   BOOLEAN NOT NULL DEFAULT FALSE" in db.SCHEMA_SQL
    assert "ALTER TABLE food ADD COLUMN IF NOT EXISTS pantry_staple BOOLEAN NOT NULL DEFAULT FALSE" \
        in db.MIGRATIONS_SQL


def test_le_corps_accepte_le_drapeau_et_ne_l_impose_pas():
    assert app_module.FoodBody(name="cumin").pantry_staple is None
    assert app_module.FoodBody(name="cumin", pantry_staple=True).pantry_staple is True


def test_la_liste_rend_le_drapeau():
    assert "f.pantry_staple" in inspect.getsource(inspect.unwrap(app_module.list_food))


def test_put_garde_le_drapeau_s_il_n_est_pas_dit():
    source = inspect.getsource(inspect.unwrap(app_module.update_food))
    assert "pantry_staple = COALESCE($8, pantry_staple)" in source


def test_post_pose_faux_par_defaut():
    source = inspect.getsource(inspect.unwrap(app_module.create_food))
    assert "bool(body.pantry_staple)" in source

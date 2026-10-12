"""Unitaires — référentiel de présence."""

from datetime import date

import pytest

from cooking_manager.presence import (
    Absence,
    ChildWeekUnknown,
    CustodyInfo,
    HouseholdConfig,
    Referential,
    SchoolPeriod,
    Stay,
    attendees,
    children_present_this_week,
    parse_referential,
    uncomposed_slots,
    week_grid,
)

SUMMER = SchoolPeriod("Vacances d'été 2026", date(2026, 7, 4), date(2026, 8, 31))

class TestCustodyCycle:
    def test_reference_week_has_children(self):
        assert children_present_this_week(date(2026, 3, 10)) is True

    def test_alternates_every_other_week(self):
        assert children_present_this_week(date(2026, 3, 17)) is False
        assert children_present_this_week(date(2026, 3, 24)) is True

    def test_same_answer_all_week(self):
        monday, sunday = date(2026, 3, 10), date(2026, 3, 15)
        assert children_present_this_week(monday) == children_present_this_week(sunday)

class TestCanteen:
    """Mardi/jeudi/vendredi midi : enfants à la cantine — mais SEULEMENT en"""

    SCHOOL_TUESDAY = date(2026, 3, 10)
    HOLIDAY_TUESDAY = date(2026, 8, 11)

    def test_canteen_applies_during_school(self):
        assert attendees(self.SCHOOL_TUESDAY, "lunch") == ["Julien", "Claire"]

    def test_canteen_does_not_apply_during_holidays(self):
        """LE cas de l'incident : en août, les enfants sont là à midi."""
        ref = Referential(school_holidays=[SUMMER])
        assert attendees(self.HOLIDAY_TUESDAY, "lunch", ref) == [
            "Julien", "Claire", "Lou", "Tom"
        ]

    def test_without_referential_the_answer_is_wrong(self):
        """Sans référentiel, la règle cantine s'applique à tort — c'est"""
        assert "Lou" not in attendees(self.HOLIDAY_TUESDAY, "lunch")

    def test_dinner_is_never_canteen(self):
        ref = Referential(school_holidays=[SUMMER])
        assert "Lou" in attendees(self.SCHOOL_TUESDAY, "dinner", ref)

    def test_wednesday_lunch_is_never_canteen(self):
        assert "Lou" in attendees(date(2026, 3, 11), "lunch")

class TestGcalCustodyPattern:
    """Non-régression : la semaine des enfants se lit dans un agenda partagé."""

    MONDAY = date(2026, 9, 7)
    GCAL_HOUSEHOLD = HouseholdConfig(
        children=[CustodyInfo(name=n, pattern="gcal") for n in ("Lou", "Tom")],
    )

    def test_synced_week_with_children(self):
        ref = Referential(gcal_weeks={self.MONDAY: True})
        assert attendees(self.MONDAY, "dinner", ref, self.GCAL_HOUSEHOLD) == [
            "Julien", "Claire", "Lou", "Tom"
        ]

    def test_synced_week_without_children(self):
        ref = Referential(gcal_weeks={self.MONDAY: False})
        assert attendees(self.MONDAY, "dinner", ref, self.GCAL_HOUSEHOLD) == [
            "Julien", "Claire"
        ]

    def test_unsynced_week_refuses_rather_than_guesses(self):
        """LE cas de l'incident : semaine inconnue != enfants absents."""
        with pytest.raises(ChildWeekUnknown):
            attendees(self.MONDAY, "dinner", Referential(), self.GCAL_HOUSEHOLD)

    def test_any_day_resolves_to_its_monday(self):
        ref = Referential(gcal_weeks={self.MONDAY: True})
        friday = date(2026, 9, 11)
        assert "Lou" in attendees(friday, "dinner", ref, self.GCAL_HOUSEHOLD)

class TestAbsences:
    def test_absent_person_is_removed(self):
        ref = Referential(
            school_holidays=[SUMMER],
            absences=[Absence("Claire", date(2026, 8, 4), date(2026, 8, 6), "voyage")],
        )
        assert "Claire" not in attendees(date(2026, 8, 5), "dinner", ref)
        assert "Claire" in attendees(date(2026, 8, 7), "dinner", ref)

    def test_no_adult_means_no_home_meal(self):
        """Des enfants ne peuvent pas être les seuls convives d'un repas maison :"""
        ref = Referential(
            school_holidays=[SUMMER],
            absences=[
                Absence("Julien", date(2026, 8, 8), date(2026, 8, 16), "Bordeaux"),
                Absence("Claire", date(2026, 8, 8), date(2026, 8, 16), "Bordeaux"),
            ],
        )
        assert attendees(date(2026, 8, 10), "dinner", ref) == []

class TestStays:
    """Le correctif du bug fondateur (F.30, Talence 2026-08-10) : en location de"""

    TALENCE = Stay(
        label="Semaine à Talence",
        start=date(2026, 8, 8), end=date(2026, 8, 16),
        members=["Julien", "Claire", "Lou", "Tom"],
        cooking=True, location="Talence",
    )

    def test_stay_members_are_at_the_table(self):
        ref = Referential(school_holidays=[SUMMER], stays=[self.TALENCE])
        assert attendees(date(2026, 8, 10), "dinner", ref) == [
            "Julien", "Claire", "Lou", "Tom"
        ]

    def test_stay_beats_absence(self):
        """Le bug exact : les adultes marqués 'à Bordeaux/absents' vidaient la"""
        ref = Referential(
            school_holidays=[SUMMER],
            absences=[
                Absence("Julien", date(2026, 8, 8), date(2026, 8, 16), "Bordeaux"),
                Absence("Claire", date(2026, 8, 8), date(2026, 8, 16), "Bordeaux"),
            ],
            stays=[self.TALENCE],
        )
        assert attendees(date(2026, 8, 10), "lunch", ref) == [
            "Julien", "Claire", "Lou", "Tom"
        ]

    def test_stay_ignores_canteen_frame(self):
        """Un mardi midi de séjour : pas de cantine, tout le monde à table."""
        ref = Referential(school_holidays=[SUMMER], stays=[self.TALENCE])
        assert "Lou" in attendees(date(2026, 8, 11), "lunch", ref)

    def test_outside_the_stay_the_frame_applies(self):
        """Hors période de séjour, le stay n'a aucun effet : la trame reprend."""
        day = date(2026, 8, 20)
        with_stay = Referential(school_holidays=[SUMMER], stays=[self.TALENCE])
        without_stay = Referential(school_holidays=[SUMMER])
        assert attendees(day, "dinner", with_stay) == attendees(day, "dinner", without_stay)

class TestSlotAbsence:
    def test_absence_limited_to_one_slot(self):
        """« déjeune au bureau ce midi » — absent au déjeuner, présent au dîner."""
        ref = Referential(
            absences=[Absence("Julien", date(2026, 3, 3), date(2026, 3, 3),
                              "bureau", slot="lunch")],
        )
        assert "Julien" not in attendees(date(2026, 3, 3), "lunch", ref)
        assert "Julien" in attendees(date(2026, 3, 3), "dinner", ref)

class TestOverrides:
    def test_override_wins_over_everything(self):
        ref = Referential(
            school_holidays=[SUMMER],
            overrides={"2026-08-04/lunch": ["Julien"]},
        )
        assert attendees(date(2026, 8, 4), "lunch", ref) == ["Julien"]

    def test_override_wins_over_stay(self):
        ref = Referential(
            stays=[TestStays.TALENCE],
            overrides={"2026-08-10/lunch": ["Julien"]},
        )
        assert attendees(date(2026, 8, 10), "lunch", ref) == ["Julien"]

class TestParseReferential:
    BODY = """
## Vacances scolaires

| Période | Début | Fin |
|---|---|---|
| **Vacances d'été 2026** | 2026-07-04 | 2026-08-31 |

## Absences

| Qui | Début | Fin | Motif |
|---|---|---|---|
| Julien | 2026-08-08 | 2026-08-16 | Bordeaux |

## Exceptions

- 2026-08-05/dinner : Julien, Claire
"""

    def test_parses_all_three_sections(self):
        ref = parse_referential(self.BODY)
        assert len(ref.school_holidays) == 1
        assert len(ref.absences) == 1
        assert ref.overrides == {"2026-08-05/dinner": ["Julien", "Claire"]}

    def test_holiday_detection(self):
        ref = parse_referential(self.BODY)
        assert ref.is_school_holiday(date(2026, 8, 4))
        assert not ref.is_school_holiday(date(2026, 9, 15))

    def test_empty_body_is_safe(self):
        """Un référentiel absent ne casse rien : la trame déterministe"""
        ref = parse_referential("")
        assert ref.school_holidays == [] and ref.absences == []
        assert attendees(date(2026, 8, 4), "dinner", ref)

class TestWeekGrid:
    def test_grid_covers_seven_days(self):
        ref = Referential(school_holidays=[SUMMER])
        grid = week_grid(date(2026, 8, 3), ref)
        assert len(grid) == 7
        assert grid[0]["day"] == "lundi" and grid[6]["day"] == "dimanche"

    def test_grid_marks_holidays(self):
        ref = Referential(school_holidays=[SUMMER])
        assert week_grid(date(2026, 8, 3), ref)[0]["school_holiday"] == "Vacances d'été 2026"


class TestUncomposedSlots:
    """Le cas qui a laissé 18 fiches dormir : une tablée sans repas, en silence (#89)."""

    def grid(self):
        return week_grid(date(2026, 9, 21), Referential(), HouseholdConfig())

    def test_a_slot_with_people_and_no_meal_is_reported(self):
        out = uncomposed_slots(self.grid(), set())
        assert out, "une semaine entière sans aucun repas doit tout remonter"
        assert {"breakfast", "lunch", "snack", "dinner"} >= {s["slot"] for s in out}

    def test_a_composed_slot_disappears(self):
        grid = self.grid()
        composed = {(row["date"], slot) for row in grid
                    for slot in ("breakfast", "lunch", "snack", "dinner")}
        assert uncomposed_slots(grid, composed) == []

    def test_an_empty_table_is_never_reported(self):
        grid = [{"date": "2026-09-21", "day": "Lundi", "breakfast": [], "lunch": [],
                 "snack": [], "dinner": []}]
        assert uncomposed_slots(grid, set()) == []

    def test_breakfast_survives_the_canteen(self):
        out = uncomposed_slots(self.grid(), set())
        assert any(s["slot"] == "breakfast" for s in out)


class TestDatesDesEcrituresDeReferentiel:
    """asyncpg refuse une chaine ou il attend une date : les trois POST en mouraient."""

    def test_les_trois_modeles_rendent_des_dates(self):
        from backend.app import AbsenceCreate, SchoolPeriodCreate, StayCreate

        absence = AbsenceCreate.model_validate(
            {"person_id": 5, "start_date": "2026-09-28",
             "end_date": "2026-09-28", "slot": "dinner"})
        periode = SchoolPeriodCreate.model_validate(
            {"label": "Toussaint", "start_date": "2026-10-17",
             "end_date": "2026-11-02"})
        sejour = StayCreate.model_validate(
            {"label": "Talence", "start_date": "2026-08-10",
             "end_date": "2026-08-16"})
        for modele in (absence, periode, sejour):
            assert isinstance(modele.start_date, date), type(modele.start_date)
            assert isinstance(modele.end_date, date), type(modele.end_date)

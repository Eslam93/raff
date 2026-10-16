"""The lending rules for holds and renewals: their settings, the renewal due date, the pick-up
date, and the holds sweep that runs while the app is up.
"""

import asyncio
from datetime import UTC, date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.activity import format_short_day
from app.services.circulation import renewed_due_at
from app.services.holds import pickup_by_for

TODAY = date(2026, 10, 16)


def make_settings(**values):
    return Settings(_env_file=None, **values)


def end_of(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59, tzinfo=UTC))


def test_lending_rule_defaults(monkeypatch):
    for name in ("HOLD_PICKUP_DAYS", "MAX_OPEN_HOLDS", "MAX_RENEWALS", "HOLD_SWEEP_SECONDS"):
        monkeypatch.delenv(name, raising=False)

    settings = make_settings()

    assert settings.hold_pickup_days == 3
    assert settings.max_open_holds == 5
    assert settings.max_renewals == 2
    assert settings.hold_sweep_seconds == 60


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("hold_pickup_days", 0),
        ("hold_pickup_days", 15),
        ("max_open_holds", 0),
        ("max_open_holds", 51),
        ("max_renewals", -1),
        ("max_renewals", 11),
        ("hold_sweep_seconds", -1),
    ],
)
def test_lending_rules_outside_their_bounds_are_rejected(name, value):
    with pytest.raises(ValidationError, match=name):
        make_settings(**{name: value})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("hold_pickup_days", 1),
        ("hold_pickup_days", 14),
        ("max_open_holds", 1),
        ("max_open_holds", 50),
        ("max_renewals", 0),
        ("max_renewals", 10),
        ("hold_sweep_seconds", 0),
    ],
)
def test_lending_rules_at_their_bounds_are_accepted(name, value):
    assert getattr(make_settings(**{name: value}), name) == value


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        # Due later than today: the loan period is added to the due date.
        (end_of(TODAY + timedelta(days=5)), end_of(TODAY + timedelta(days=19))),
        # Due today: from today.
        (end_of(TODAY), end_of(TODAY + timedelta(days=14))),
        # Overdue: from today, not from the past due date.
        (end_of(TODAY - timedelta(days=6)), end_of(TODAY + timedelta(days=14))),
        # Never more than 90 days from today.
        (end_of(TODAY + timedelta(days=85)), end_of(TODAY + timedelta(days=90))),
        (end_of(TODAY + timedelta(days=90)), end_of(TODAY + timedelta(days=90))),
    ],
)
def test_a_renewal_moves_the_due_date_from_the_later_of_today_and_the_due_date(due, expected):
    assert renewed_due_at(due, today=TODAY, loan_period_days=14) == expected


def test_the_renewal_reads_the_due_date_as_a_utc_day():
    # 01:00 on the 22nd in UTC+3 is 22:00 on the 21st in UTC.
    due = datetime(2026, 10, 22, 1, 0, tzinfo=UTC) - timedelta(hours=3)

    assert renewed_due_at(due, today=TODAY, loan_period_days=7) == end_of(date(2026, 10, 28))


def test_a_ready_hold_is_picked_up_by_the_end_of_its_last_day_in_utc():
    pickup_by = pickup_by_for(3)

    assert pickup_by == end_of(datetime.now(UTC).date() + timedelta(days=3))


def test_short_days_name_the_day_and_month():
    assert format_short_day(date(2026, 10, 19)) == "19 Oct"


async def test_the_app_runs_the_holds_sweep_while_up_and_stops_it_on_shutdown(make_app, serve):
    app = make_app(hold_sweep_seconds=60)

    async with serve(app):
        sweeper = app.state.hold_sweeper
        await asyncio.sleep(0)
        assert sweeper is not None
        assert not sweeper.done()

    assert sweeper.cancelled()


async def test_hold_sweep_seconds_0_turns_the_sweep_off(make_app, serve):
    app = make_app(hold_sweep_seconds=0)

    async with serve(app):
        assert app.state.hold_sweeper is None

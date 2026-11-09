"""Timecard view of an employee's punches for one shift.

Exceptions need an "original timecard" (check-in, check-out, meal start/end, total hours) that
the API, the UI and the LLM prompt all read. This module builds it from punches and extracts it
from a stored attendance dict.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

TIMECARD_KEYS = ("checkIn", "checkOut", "mealStart", "mealEnd")


def _hhmm(ts: datetime | None) -> str | None:
    return ts.strftime("%H:%M") if ts else None


def _kind(p: Any) -> str:
    return str(getattr(p.punch_type, "value", p.punch_type))


def shift_window(punches: Sequence[Any], day: str) -> list[Any]:
    """Punches that belong to the shift of ``day``, oldest first.

    A shift belongs to the day of its first clock-in, so an overnight shift includes punches
    after midnight, up to the next day's first clock-in.
    """
    target = datetime.fromisoformat(day).date()
    ordered = sorted(punches, key=lambda p: p.timestamp)
    ins_today = [p for p in ordered if _kind(p) == "IN" and p.timestamp.date() == target]
    if not ins_today:
        return [p for p in ordered if p.timestamp.date() == target]
    start = ins_today[0].timestamp
    later_ins = [p.timestamp for p in ordered if _kind(p) == "IN" and p.timestamp.date() > target]
    end = later_ins[0] if later_ins else start + timedelta(days=2)
    return [p for p in ordered if start <= p.timestamp < end]


def build_timecard(punches: Sequence[Any], day: str) -> dict[str, Any]:
    """Original timecard for one employee-day, from that shift's punches.

    Duplicate taps do not matter here: only the first clock-in, the last clock-out after it and
    the first break pair are used. (The raw punches, duplicates included, are shown separately.)
    """
    window = shift_window(punches, day)
    kind = _kind

    def first(k: str) -> datetime | None:
        return next((p.timestamp for p in window if kind(p) == k), None)

    check_in = first("IN")
    # With no clock-in at all (a missing clock-in) the recorded clock-out must still be shown
    outs = [
        p.timestamp
        for p in window
        if kind(p) == "OUT" and (check_in is None or p.timestamp > check_in)
    ]
    check_out = max(outs) if outs else None
    meal_start, meal_end = first("BREAK_START"), first("BREAK_END")

    total = None
    if check_in and check_out:
        worked = check_out - check_in
        if meal_start and meal_end and meal_end > meal_start:
            worked -= meal_end - meal_start
        total = round(worked.total_seconds() / 3600, 2)
    return {
        "checkIn": _hhmm(check_in),
        "checkOut": _hhmm(check_out),
        "mealStart": _hhmm(meal_start),
        "mealEnd": _hhmm(meal_end),
        "totalHours": total,
    }


def timecard_view(attendance: dict[str, Any] | None) -> dict[str, Any]:
    """Only the timecard fields of a stored attendance dict (ignores any detector details)."""
    data = attendance or {}
    view: dict[str, Any] = {k: data.get(k) for k in TIMECARD_KEYS}
    if "totalHours" in data:
        view["totalHours"] = data["totalHours"]
    return view


def employee_shifts(punches: Sequence[Any]) -> list[tuple[str, datetime, datetime | None]]:
    """(date, first clock-in, last clock-out or None) for each worked shift, oldest first."""
    days = sorted({p.timestamp.date().isoformat() for p in punches if _kind(p) == "IN"})
    shifts: list[tuple[str, datetime, datetime | None]] = []
    for day in days:
        window = shift_window(punches, day)
        start = min(p.timestamp for p in window if _kind(p) == "IN")
        outs = [p.timestamp for p in window if _kind(p) == "OUT" and p.timestamp > start]
        shifts.append((day, start, max(outs) if outs else None))
    return shifts


def shift_context(
    punches: Sequence[Any],
    exception_type: str,
    day: str,
    min_rest_hours: float = 8.0,
    max_consecutive_days: int = 6,
) -> tuple[list[dict[str, Any]], str | None]:
    """The other shifts that explain a rest-period or consecutive-days exception.

    These two exceptions are about several days, so one day's timecard looks normal. Returns
    (shifts to show, one-line summary).
    """
    shifts = employee_shifts(punches)
    idx = next((i for i, s in enumerate(shifts) if s[0] == day), None)
    if idx is None:
        return [], None

    def item(s: tuple[str, datetime, datetime | None]) -> dict[str, Any]:
        return {
            "date": s[0],
            "start": _hhmm(s[1]),
            "end": _hhmm(s[2]),
            "end_date": s[2].date().isoformat() if s[2] and s[2].date() != s[1].date() else None,
        }

    if exception_type == "rest_period" and idx > 0:
        prev, cur = shifts[idx - 1], shifts[idx]
        summary = None
        if prev[2] is not None:
            rest = (cur[1] - prev[2]).total_seconds() / 3600
            summary = (
                f"Only {rest:.1f} hours of rest between these two shifts "
                f"(the minimum is {min_rest_hours:.1f})."
            )
        return [item(prev), item(cur)], summary

    if exception_type == "consecutive_days":
        first = idx
        while first > 0 and shifts[first][1].date() - shifts[first - 1][1].date() == timedelta(
            days=1
        ):
            first -= 1
        run = shifts[first : idx + 1]
        return [item(s) for s in run], (
            f"This is day {len(run)} worked in a row (the maximum is {max_consecutive_days} "
            "without a day off)."
        )
    return [], None

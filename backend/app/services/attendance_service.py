"""Daily attendance records, worked out from stored punches and schedules.

Status is decided by code from the data: no punches on a scheduled day is Absent, a first
clock-in after the schedule start plus the grace period is Late, anything else is Present.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EmployeeModel, ExceptionModel, PunchModel, ScheduleModel
from app.rules.detectors.schedule_conflict import ScheduleConflictConfig
from app.schemas.attendance import (
    AttendanceDay,
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSummary,
    DayCount,
    WeekRate,
)
from app.services.timecard import build_timecard

LATE_GRACE = timedelta(minutes=ScheduleConflictConfig().late_grace_period_minutes)


def _hhmm(ts: datetime) -> str:
    return ts.strftime("%H:%M")


def data_date_range(db: Session) -> tuple[str | None, str | None]:
    """Earliest and latest date that has a punch or a schedule."""
    dates: list[str] = []
    for col in (func.min(ScheduleModel.date), func.max(ScheduleModel.date)):
        value = db.execute(select(col)).scalar()
        if value:
            dates.append(str(value))
    for pcol in (func.min(PunchModel.timestamp), func.max(PunchModel.timestamp)):
        stamp = db.execute(select(pcol)).scalar()
        if stamp:
            dates.append(stamp.date().isoformat() if hasattr(stamp, "date") else str(stamp)[:10])
    return (min(dates), max(dates)) if dates else (None, None)


def people_by_day(db: Session) -> dict[str, set[str]]:
    """Employees scheduled or punching, for each date that has any data."""
    people: dict[str, set[str]] = defaultdict(set)
    for emp_id, day in db.execute(select(ScheduleModel.employee_id, ScheduleModel.date)):
        people[str(day)].add(emp_id)
    for emp_id, stamp in db.execute(select(PunchModel.employee_id, PunchModel.timestamp)):
        people[stamp.date().isoformat()].add(emp_id)
    return people


def busiest_date(db: Session) -> str | None:
    """The date with the most employees scheduled or punching (latest wins a tie)."""
    people = people_by_day(db)
    return max(people, key=lambda d: (len(people[d]), d)) if people else None


def attendance_for_day(db: Session, day: str | None = None) -> AttendanceDay:
    """Attendance records for ``day`` (default: the busiest date)."""
    min_date, max_date = data_date_range(db)
    day = day or busiest_date(db) or max_date or datetime.now(UTC).date().isoformat()
    target = datetime.fromisoformat(day).date()

    employees = {e.id: e for e in db.scalars(select(EmployeeModel))}
    schedules = {
        s.employee_id: s for s in db.scalars(select(ScheduleModel).where(ScheduleModel.date == day))
    }
    # Overnight shifts reach into the next day, and a shift belongs to the day it starts.
    window_start = datetime.combine(target - timedelta(days=1), datetime.min.time())
    window_end = datetime.combine(target + timedelta(days=2), datetime.min.time())
    punches_by_emp: dict[str, list[PunchModel]] = defaultdict(list)
    for p in db.scalars(
        select(PunchModel).where(
            PunchModel.timestamp >= window_start, PunchModel.timestamp < window_end
        )
    ):
        punches_by_emp[p.employee_id].append(p)
    exceptions_by_emp: dict[str, list[str]] = defaultdict(list)
    for exc_id, emp_id in db.execute(
        select(ExceptionModel.id, ExceptionModel.employee_id)
        .where(ExceptionModel.date == day)
        .order_by(ExceptionModel.id)
    ):
        exceptions_by_emp[emp_id].append(exc_id)

    records: list[AttendanceRecord] = []
    for emp_id, emp in employees.items():
        sched = schedules.get(emp_id)
        card = build_timecard(punches_by_emp.get(emp_id, []), day)
        worked = card["checkIn"] is not None or card["checkOut"] is not None
        if not sched and not worked:
            continue  # a day off: nothing scheduled and nothing worked

        status: AttendanceStatus = "Present" if worked else "Absent"
        first_in = min(
            (
                p.timestamp
                for p in punches_by_emp.get(emp_id, [])
                if str(getattr(p.punch_type, "value", p.punch_type)) == "IN"
                and p.timestamp.date() == target
            ),
            default=None,
        )
        if sched and first_in and first_in > sched.start_time + LATE_GRACE:
            status = "Late"
        records.append(
            AttendanceRecord(
                employee_id=emp_id,
                name=emp.name,
                department=emp.department,
                shift=emp.shift,
                scheduled_start=_hhmm(sched.start_time) if sched else None,
                scheduled_end=_hhmm(sched.end_time) if sched else None,
                check_in=card["checkIn"],
                check_out=card["checkOut"],
                status=status,
                exception_ids=exceptions_by_emp.get(emp_id, []),
            )
        )
    records.sort(key=lambda r: (r.name.lower(), r.employee_id))
    return AttendanceDay(date=day, min_date=min_date, max_date=max_date, records=records)


def _counts(records: list[AttendanceRecord]) -> tuple[int, int, int]:
    present = sum(1 for r in records if r.status == "Present")
    late = sum(1 for r in records if r.status == "Late")
    return present, late, len(records) - present - late


def attendance_summary(db: Session, day: str | None = None, weeks: int = 6) -> AttendanceSummary:
    """Dashboard numbers for ``day`` (default: the busiest date), all from stored data.

    Returns the day's present/late/absent counts, the Monday-to-Sunday week around it, and the
    share of scheduled-or-working people who actually worked for each of the last ``weeks`` weeks.
    """
    people = people_by_day(db)
    day = day or busiest_date(db) or datetime.now(UTC).date().isoformat()
    ref = datetime.fromisoformat(day).date()
    present, late, absent = _counts(attendance_for_day(db, day).records)

    def daily(d: datetime) -> tuple[int, int, int]:
        iso = d.date().isoformat()
        return _counts(attendance_for_day(db, iso).records) if iso in people else (0, 0, 0)

    monday = datetime.combine(ref - timedelta(days=ref.weekday()), datetime.min.time())
    day_counts = []
    for i in range(7):
        d = monday + timedelta(days=i)
        p, lt, ab = daily(d)
        day_counts.append(
            DayCount(
                date=d.date().isoformat(), label=d.strftime("%a"), present=p, late=lt, absent=ab
            )
        )

    exception_dates = [str(d) for (d,) in db.execute(select(ExceptionModel.date))]
    week_rates = []
    for back in range(weeks - 1, -1, -1):
        start = monday - timedelta(weeks=back)
        p_total = l_total = a_total = 0
        for i in range(7):
            p, lt, ab = daily(start + timedelta(days=i))
            p_total, l_total, a_total = p_total + p, l_total + lt, a_total + ab
        scheduled = p_total + l_total + a_total
        week_days = {(start + timedelta(days=i)).date().isoformat() for i in range(7)}
        week_rates.append(
            WeekRate(
                week=f"W{start.isocalendar().week:02d}",
                start=start.date().isoformat(),
                rate=round(100 * (p_total + l_total) / scheduled, 1) if scheduled else None,
                exceptions=sum(1 for d in exception_dates if d in week_days),
            )
        )

    return AttendanceSummary(
        date=day,
        total_employees=db.scalar(select(func.count(EmployeeModel.id))) or 0,
        departments=db.scalar(select(func.count(func.distinct(EmployeeModel.department)))) or 0,
        scheduled=present + late + absent,
        present=present,
        late=late,
        absent=absent,
        days=day_counts,
        weeks=week_rates,
    )

# Diagram: attendance_engine.py — @on_event("clock.out")

from datetime import datetime
from typing import Optional

import sqlite3

from hr_bot.policy import CompanyPolicy
from hr_bot.services.ai_service import AIService


def calc_hours(clock_in: datetime, clock_out: datetime) -> float:
    return round((clock_out - clock_in).total_seconds() / 3600, 2)


def is_late(clock_in: datetime, policy: CompanyPolicy) -> bool:
    return clock_in.hour > policy.late_hour or (
        clock_in.hour == policy.late_hour and clock_in.minute > policy.late_minute
    )


def process_clock_out(
    db,
    emp_id: int,
    clock_in_iso: str,
    clock_out_iso: str,
    work_date: Optional[str],
    policy: CompanyPolicy,
) -> dict:
    ci = datetime.fromisoformat(clock_in_iso)
    co = datetime.fromisoformat(clock_out_iso)
    hours = calc_hours(ci, co)
    ot = round(max(0.0, hours - policy.workday_hours), 2)
    late = is_late(ci, policy)

    ai_flagged, flag_reason = 0, None
    if ot > policy.max_ot_per_day or late:
        ai_flagged = 1
        flag_reason = (
            f"OT {ot} ชม. เกินนโยบาย {policy.max_ot_per_day} ชม./วัน"
            if ot > policy.max_ot_per_day
            else "เข้างานสายตามนโยบาย"
        )
        AIService.flag(emp_id, "attendance_anomaly", flag_reason)

    wd = work_date or ci.date().isoformat()

    db.execute(
        """INSERT INTO attendance (emp_id,work_date,clock_in,clock_out,hours_worked,ot_hours,is_late,ai_flagged,flag_reason)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (emp_id, wd, clock_in_iso, clock_out_iso, hours, ot, 1 if late else 0, ai_flagged, flag_reason),
    )
    db.commit()

    return {
        "emp_id": emp_id,
        "work_date": wd,
        "hours_worked": hours,
        "ot_hours": ot,
        "is_late": late,
        "ai_flagged": bool(ai_flagged),
        "flag_reason": flag_reason,
    }


def insert_attendance_safe(db, emp_id: int, clock_in_iso: str, clock_out_iso: str, work_date: Optional[str], policy: CompanyPolicy) -> dict:
    try:
        return process_clock_out(db, emp_id, clock_in_iso, clock_out_iso, work_date, policy)
    except sqlite3.IntegrityError as e:
        raise ValueError("Attendance record already exists for this date") from e

"""Business rules — OT caps, late threshold (diagram attendance / payroll)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CompanyPolicy:
    workday_hours: float = 8.0
    max_ot_per_day: float = 3.0
    max_ot_per_month: float = 40.0
    late_hour: int = 9
    late_minute: int = 0


DEFAULT_POLICY = CompanyPolicy()

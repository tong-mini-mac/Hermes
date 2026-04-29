"""Tax ladder + SSO — shared by payroll engine."""

from typing import Any


def calc_tax_monthly(annual_gross: float, profile: dict) -> float:
    deductions = (
        profile.get("personal_deduction", 60000)
        + profile.get("spouse_deduction", 0)
        + profile.get("child_deduction", 0)
        + profile.get("insurance_deduction", 0)
        + profile.get("provident_fund", 0)
        + min(annual_gross * 0.50, 100000)
    )
    taxable = max(0, annual_gross - deductions)
    brackets = [(150000, 0), (150000, 0.05), (200000, 0.10), (250000, 0.15), (250000, 0.20), (float("inf"), 0.35)]
    tax, remaining = 0.0, taxable
    for limit, rate in brackets:
        chunk = min(remaining, limit)
        tax += chunk * rate
        remaining -= chunk
        if remaining <= 0:
            break
    return round(tax / 12, 2)


def calc_sso_monthly(gross: float) -> float:
    return round(min(gross, 15000) * 0.05, 2)


def detect_payroll_anomaly(prev_net: float, net: float) -> tuple:
    if prev_net == 0:
        return False, None
    change_pct = abs(net - prev_net) / prev_net * 100
    if change_pct > 15:
        return True, f"เงินเดือนเปลี่ยนแปลง {change_pct:.1f}% จากเดือนที่แล้ว"
    return False, None

"""AI layer — pattern / anomaly flags (diagram: AIService.flag, flag_anomaly)."""

from typing import Optional


class AIService:
    """Rule-based stand-in for ML; swap with real model later."""

    @staticmethod
    def flag(emp_id: int, reason_code: str, detail: Optional[str] = None) -> dict:
        return {"emp_id": emp_id, "code": reason_code, "detail": detail}

    @staticmethod
    def flag_anomaly(emp_id: int, net: float, prev_net: float) -> Optional[dict]:
        from hr_bot.finance_math import detect_payroll_anomaly

        flagged, reason = detect_payroll_anomaly(prev_net, net)
        if flagged:
            return AIService.flag(emp_id, "payroll_anomaly", reason)
        return None

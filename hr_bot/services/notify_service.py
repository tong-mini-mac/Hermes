"""Notifications — diagram NotifyService.alert_manager / sms_email / email / in-app."""

from typing import Optional


class NotifyService:
    @staticmethod
    def alert_manager(manager_id: Optional[int]) -> Optional[str]:
        if manager_id is None:
            return None
        return f"[notify] manager_id={manager_id}: พนักงานใหม่เข้าระบบ"

    @staticmethod
    def sms_email(emp_id: int, msg: str) -> str:
        return f"[sms/email] emp_id={emp_id}: {msg}"

    @staticmethod
    def send_email(emp_id: int, payslip_ref: str) -> str:
        return f"[email] emp_id={emp_id}: payslip={payslip_ref}"

    @staticmethod
    def send_inapp(emp_id: int, payslip_ref: str) -> str:
        return f"[in-app] emp_id={emp_id}: payslip={payslip_ref}"

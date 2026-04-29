# Diagram: event_handler.py — @on_event("employee.created")
# Implements parallel dispatch after HR submits one-shot onboarding form.

from typing import Any, Dict, Optional

from hr_bot.events import on_event
from hr_bot.services.notify_service import NotifyService


@on_event("employee.created")
def handle_new_employee(emp_id: int, employment_type: str = "full-time", manager_id: Optional[int] = None) -> Dict[str, Any]:
    """Diagram snippet — EmployeeService.create + Leave/Tax/Payroll init + Notify."""
    emp_type = employment_type

    actions = [
        f"Employee profile id={emp_id}",
        f"LeaveService.init_quota({emp_id}, {emp_type})",
        f"TaxService.init_profile({emp_id})",
        f"PayrollService.register({emp_id})",
    ]
    msg = NotifyService.alert_manager(manager_id)
    if msg:
        actions.append(msg)
    return {"status": "onboarding_complete", "actions": actions}

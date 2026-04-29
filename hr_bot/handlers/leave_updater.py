# Diagram — @on_event("leave.approved")

from datetime import datetime

from hr_bot.services.notify_service import NotifyService


def update_leave_after_approval(db, leave_id: int, approved_by_user_id: int) -> dict:
    leave = db.execute("SELECT * FROM leave_requests WHERE id=?", (leave_id,)).fetchone()
    if not leave:
        raise ValueError("Leave request not found")
    lr = dict(leave)
    if lr["status"] != "pending":
        raise ValueError("Leave already decided")

    db.execute(
        "UPDATE leave_requests SET status=?, approved_by=?, decided_at=? WHERE id=?",
        ("approved", approved_by_user_id, datetime.now().isoformat(), leave_id),
    )

    leave_type = lr["leave_type"]
    days = lr["days"]
    emp_id = lr["emp_id"]
    year = datetime.now().year

    db.execute(
        f"UPDATE leave_quota SET {leave_type}_used = {leave_type}_used + ? WHERE emp_id=? AND year=?",
        (days, emp_id, year),
    )

    msg = NotifyService.sms_email(emp_id, "ใบลาของคุณได้รับการอนุมัติแล้ว")
    actions = ["อัปเดต Leave Quota", "Mark attendance leave [simulated]", msg]

    db.commit()
    return {"leave_id": leave_id, "status": "approved", "code_bot_actions": actions}

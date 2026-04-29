# Diagram: payroll_engine.py — @cron("0 8 28 * *") + aggregators

from datetime import datetime
from typing import List

from hr_bot.finance_math import calc_sso_monthly, calc_tax_monthly, detect_payroll_anomaly
from hr_bot.services.ai_service import AIService
from hr_bot.services.prism_service import PRISMService


def run_payroll_batch(db, month: int, year: int) -> dict:
    employees = db.execute("SELECT * FROM employees WHERE status='active'").fetchall()
    if not employees:
        raise ValueError("ไม่มีพนักงาน")

    existing = db.execute("SELECT id FROM payroll WHERE month=? AND year=?", (month, year)).fetchone()
    if existing:
        raise ValueError(f"Payroll เดือน {month}/{year} มีอยู่แล้ว (id={existing['id']})")

    cur = db.execute("INSERT INTO payroll (month,year) VALUES (?,?)", (month, year))
    payroll_id = cur.lastrowid

    total_gross = total_tax = total_sso = total_net = 0.0
    ai_flags = 0
    items: List[dict] = []

    for emp_row in employees:
        emp = dict(emp_row)
        ot_data = db.execute(
            """SELECT SUM(ot_hours) as total_ot FROM attendance
               WHERE emp_id=? AND strftime('%m-%Y', work_date)=?""",
            (emp["id"], f"{month:02d}-{year}"),
        ).fetchone()
        ot_hours = float(ot_data["total_ot"] or 0)
        if ot_hours > 40:
            AIService.flag(emp["id"], "ot_monthly_excess", f"OT รวม {ot_hours:.0f} ชม. เกินนโยบาย 40 ชม./เดือน")

        ot_rate = emp["salary"] / 26 / 8 * 1.5 if emp["salary"] else 0
        ot_pay = round(float(ot_hours) * ot_rate, 2)

        tax_profile = db.execute("SELECT * FROM tax_profiles WHERE emp_id=?", (emp["id"],)).fetchone()
        tax_profile = dict(tax_profile) if tax_profile else {}

        comm = PRISMService.get_commission(emp["id"], db)
        allow = 0.0
        bonus = 0.0

        gross = float(emp["salary"]) + ot_pay + comm + allow + bonus
        tax = calc_tax_monthly(gross * 12, tax_profile)
        sso = calc_sso_monthly(gross)
        net = round(gross - tax - sso, 2)

        prev = db.execute(
            """SELECT pi.net FROM payroll_items pi JOIN payroll p ON pi.payroll_id=p.id
               WHERE pi.emp_id=? AND (p.year*12+p.month) < ? ORDER BY (p.year*12+p.month) DESC LIMIT 1""",
            (emp["id"], year * 12 + month),
        ).fetchone()
        prev_net = float(dict(prev)["net"]) if prev else 0.0

        flagged, flag_reason = detect_payroll_anomaly(prev_net, net)
        if flagged:
            AIService.flag_anomaly(emp["id"], net, prev_net)
            ai_flags += 1

        change_pct = round(abs(net - prev_net) / prev_net * 100 if prev_net else 0.0, 1)

        db.execute(
            """INSERT INTO payroll_items
               (payroll_id,emp_id,base_salary,ot_pay,commission,gross,tax,sso,net,prev_net,change_pct,ai_flagged,flag_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payroll_id,
                emp["id"],
                emp["salary"],
                ot_pay,
                comm,
                gross,
                tax,
                sso,
                net,
                prev_net,
                change_pct,
                int(flagged),
                flag_reason,
            ),
        )

        total_gross += gross
        total_tax += tax
        total_sso += sso
        total_net += net
        items.append({"emp_id": emp["id"], "net": net, "ai_flagged": int(flagged), "flag_reason": flag_reason})

    db.execute(
        """UPDATE payroll SET total_gross=?,total_tax=?,total_sso=?,total_net=?,headcount=?,ai_flags=?
           WHERE id=?""",
        (
            round(total_gross, 2),
            round(total_tax, 2),
            round(total_sso, 2),
            round(total_net, 2),
            len(employees),
            ai_flags,
            payroll_id,
        ),
    )
    db.commit()

    flagged_count = sum(1 for i in items if i["ai_flagged"])
    ai_summary = {
        "ai_summary": f"Payroll เดือนนี้ปกติ {len(items)-flagged_count}/{len(items)} คน",
        "flagged_count": flagged_count,
        "flagged_items": [{"emp_id": i["emp_id"], "reason": i["flag_reason"]} for i in items if i["ai_flagged"]],
        "recommendation": (
            "กรุณาตรวจสอบรายการที่ Flag ก่อน Approve" if flagged_count else "ทุกรายการปกติ สามารถ Approve ได้เลย"
        ),
    }

    return {
        "payroll_id": payroll_id,
        "month": month,
        "year": year,
        "headcount": len(employees),
        "total_gross": round(total_gross, 2),
        "total_net": round(total_net, 2),
        "ai_flags": ai_flags,
        **ai_summary,
        "next_step": "POST /payroll/{id}/hr_approve → HR ตรวจสอบ",
    }


def cron_payroll_expression() -> str:
    """Diagram: 0 8 28 * * — run payroll morning of the 28th."""
    return "0 8 28 * *"

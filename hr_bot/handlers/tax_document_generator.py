# Diagram — generate_tax_docs after payroll.approved

from datetime import datetime

from hr_bot.services.deadline_service import DeadlineService
from hr_bot.services.tax_builders import PND1Builder, PND1KorBuilder, SSOBuilder


def generate_tax_documents(db, month: int, year: int) -> dict:
    payroll = db.execute(
        "SELECT * FROM payroll WHERE month=? AND year=? AND status='paid'",
        (month, year),
    ).fetchone()
    if not payroll:
        raise ValueError(f"ไม่พบ Payroll เดือน {month}/{year} ที่จ่ายแล้ว")

    p = dict(payroll)
    docs_created = []

    pid = PND1Builder.generate(db, month, year, p["total_gross"], p["total_tax"], p["headcount"])
    docs_created.append({"type": "ภ.ง.ด.1", "id": pid, "deadline": "วันที่ 7 เดือนถัดไป"})
    DeadlineService.remind(doc="PND1", due="วันที่ 7", alert_days=3)

    sid = SSOBuilder.generate(db, month, year, p["total_gross"], p["total_sso"], p["headcount"])
    docs_created.append({"type": "สปส.1-10", "id": sid, "deadline": "วันที่ 15 เดือนถัดไป"})
    DeadlineService.remind(doc="SSO", due="วันที่ 15", alert_days=3)

    if month == 12:
        annual = db.execute(
            """SELECT SUM(total_gross) as g, SUM(total_tax) as t, MAX(headcount) as h
               FROM payroll WHERE year=? AND status='paid'""",
            (year,),
        ).fetchone()
        if annual and dict(annual)["g"]:
            kid = PND1KorBuilder.generate_annual(
                db,
                year,
                float(dict(annual)["g"] or 0),
                float(dict(annual)["t"] or 0),
                int(dict(annual)["h"] or 0),
            )
            docs_created.append({"type": "ภ.ง.ด.1ก (ปลายปี)", "id": kid, "deadline": f"ภายใน ก.พ. {year+1}"})

    db.commit()
    return {"documents": docs_created, "next_step": "HR ตรวจสอบและยื่น RD Online / SSO Online"}

# Diagram — @on_event("payroll.approved"); dispatch_payment

from hr_bot.services.bank_file_builder import BankFileBuilder
from hr_bot.services.finance_service import FinanceService
from hr_bot.services.notify_service import NotifyService
from hr_bot.services.payslip_service import PayslipService


def dispatch_payment_for_payroll(db, payroll_id: int) -> dict:
    items = db.execute(
        """SELECT pi.*, e.name, e.bank_account, e.bank_name
           FROM payroll_items pi JOIN employees e ON pi.emp_id=e.id
           WHERE pi.payroll_id=?""",
        (payroll_id,),
    ).fetchall()

    bank_files = {}
    for row in items:
        item = dict(row)
        bank = item["bank_name"]
        bank_files.setdefault(bank, []).append({"account": item["bank_account"], "amount": item["net"], "name": item["name"]})

    built = []
    for bank, records in bank_files.items():
        built.append(BankFileBuilder.build(bank, records))

    payslip_refs = []
    for row in items:
        item = dict(row)
        ref = PayslipService.generate_pdf(item)
        payslip_refs.append(ref)
        NotifyService.send_email(item["emp_id"], ref)
        NotifyService.send_inapp(item["emp_id"], ref)

    db.execute("UPDATE payroll_items SET payslip_sent=1 WHERE payroll_id=?", (payroll_id,))

    p = db.execute("SELECT * FROM payroll WHERE id=?", (payroll_id,)).fetchone()
    p_dict = dict(p)
    totals = {
        "total_gross": p_dict["total_gross"],
        "total_net": p_dict["total_net"],
        "total_tax": p_dict["total_tax"],
        "total_sso": p_dict["total_sso"],
    }
    FinanceService.post_journal_entry(db, payroll_id, totals)

    db.execute("UPDATE payroll SET status='paid' WHERE id=?", (payroll_id,))
    db.commit()

    return {
        "payroll_id": payroll_id,
        "bank_files_created": {b["bank"]: b for b in built},
        "payslips_sent": len(items),
        "payslip_refs": payslip_refs,
        "finance_journal_entries": 4,
    }

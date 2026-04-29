"""Finance GL — diagram FinanceService.post_journal_entry."""


class FinanceService:
    @staticmethod
    def post_journal_entry(db, payroll_id: int, totals: dict) -> list:
        rows = []
        rows.append(
            ("salary_expense", "5100", totals["total_gross"], 0, "Salary Expense"),
        )
        rows.append(("net_pay", "2100", 0, totals["total_net"], "Net Pay Payable"))
        rows.append(("wht_payable", "2200", 0, totals["total_tax"], "WHT Payable → RD"))
        rows.append(("sso_payable", "2300", 0, totals["total_sso"], "SSO Payable → SSO"))
        for entry_type, acc, debit, credit, desc in rows:
            db.execute(
                "INSERT INTO finance_journal (payroll_id,entry_type,account_code,debit,credit,description) VALUES (?,?,?,?,?,?)",
                (payroll_id, entry_type, acc, debit, credit, desc),
            )
        return rows

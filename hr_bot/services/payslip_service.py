"""Diagram PayslipService.generate_pdf — returns pseudo path."""


class PayslipService:
    @staticmethod
    def generate_pdf(record: dict) -> str:
        emp_id = record.get("emp_id") or record.get("id")
        pid = record.get("payroll_id", "")
        return f"payslip_payroll{pid}_emp{emp_id}.pdf"

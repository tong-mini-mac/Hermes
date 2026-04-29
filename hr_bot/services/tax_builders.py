"""PND1 / SSO / PND1K builders — orchestrate INSERT INTO tax_documents via caller DB."""


class PND1Builder:
    @staticmethod
    def generate(db, month: int, year: int, total_gross: float, total_tax: float, headcount: int):
        cur = db.execute(
            "INSERT INTO tax_documents (doc_type,month,year,total_income,total_tax,headcount) VALUES ('PND1',?,?,?,?,?)",
            (month, year, total_gross, total_tax, headcount),
        )
        return cur.lastrowid


class SSOBuilder:
    @staticmethod
    def generate(db, month: int, year: int, total_gross: float, total_sso: float, headcount: int):
        cur = db.execute(
            "INSERT INTO tax_documents (doc_type,month,year,total_income,total_sso,headcount) VALUES ('SSO',?,?,?,?,?)",
            (month, year, total_gross, total_sso, headcount),
        )
        return cur.lastrowid


class PND1KorBuilder:
    @staticmethod
    def generate_annual(db, year: int, total_income: float, total_tax: float, headcount: int):
        cur = db.execute(
            "INSERT INTO tax_documents (doc_type,month,year,total_income,total_tax,headcount) VALUES ('PND1KOR',12,?,?,?,?)",
            (year, total_income, total_tax, headcount),
        )
        return cur.lastrowid

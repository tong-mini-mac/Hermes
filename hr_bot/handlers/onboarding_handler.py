"""Phase 1 — SQLite writes; caller commits then emit(\"employee.created\")."""

import sqlite3
from datetime import datetime


def bootstrap_new_employee(
    db,
    name: str,
    department: str,
    title: str,
    start_date: str,
    salary: float,
    employment_type: str,
    bank_account: str,
    bank_name: str,
    manager_id,
) -> int:
    cur = db.execute(
        """INSERT INTO employees (name,department,title,start_date,salary,employment_type,bank_account,bank_name,manager_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (name, department, title, start_date, salary, employment_type, bank_account, bank_name, manager_id),
    )
    emp_id = cur.lastrowid
    year = datetime.now().year
    quota = (10, 30, 3) if employment_type == "full-time" else (5, 15, 1)
    db.execute(
        "INSERT INTO leave_quota (emp_id,year,annual_total,sick_total,personal_total) VALUES (?,?,?,?,?)",
        (emp_id, year, *quota),
    )
    try:
        db.execute("INSERT INTO tax_profiles (emp_id) VALUES (?)", (emp_id,))
    except sqlite3.IntegrityError:
        pass
    return emp_id

# HERMES - Human Resource Management & Event-driven System
# Phase 1: Onboarding | Phase 2: Attendance/Leave | Phase 3: Payroll | Phase 4: Payment | Phase 5: Tax/SSO

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from enum import Enum
import sqlite3, hashlib, secrets, json, math

import hr_bot.handlers  # noqa: F401 — register @on_event handlers

from hr_bot.events import emit
from hr_bot.handlers.attendance_engine import insert_attendance_safe
from hr_bot.handlers.leave_updater import update_leave_after_approval
from hr_bot.handlers.onboarding_handler import bootstrap_new_employee
from hr_bot.handlers.payment_dispatcher import dispatch_payment_for_payroll
from hr_bot.handlers.payroll_engine import run_payroll_batch
from hr_bot.handlers.tax_document_generator import generate_tax_documents
from hr_bot.policy import DEFAULT_POLICY

app = FastAPI(
    title="HERMES - Human Resource Management & Event-driven System",
    version="2.0.0",
    description="HR System — AI + Code Bot + Human in the Loop",
)

# ═══════════════════════════════════════════
# DATABASE SETUP (SQLite)
# ═══════════════════════════════════════════

DB_PATH = "hr.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Users (Auth)
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,  -- hr_admin | manager | cfo | employee
        emp_id INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    # Tokens
    c.execute("""CREATE TABLE IF NOT EXISTS tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL
    )""")

    # Employees
    c.execute("""CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        title TEXT NOT NULL,
        start_date TEXT NOT NULL,
        salary REAL NOT NULL,
        employment_type TEXT NOT NULL,  -- full-time | part-time | contract
        bank_account TEXT NOT NULL,
        bank_name TEXT DEFAULT 'SCB',
        manager_id INTEGER,
        status TEXT DEFAULT 'active',   -- active | resigned | terminated
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    # Leave Quota
    c.execute("""CREATE TABLE IF NOT EXISTS leave_quota (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id INTEGER NOT NULL,
        year INTEGER NOT NULL,
        annual_total INTEGER DEFAULT 10,
        annual_used INTEGER DEFAULT 0,
        sick_total INTEGER DEFAULT 30,
        sick_used INTEGER DEFAULT 0,
        personal_total INTEGER DEFAULT 3,
        personal_used INTEGER DEFAULT 0,
        UNIQUE(emp_id, year)
    )""")

    # Tax Profile
    c.execute("""CREATE TABLE IF NOT EXISTS tax_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id INTEGER UNIQUE NOT NULL,
        personal_deduction REAL DEFAULT 60000,
        spouse_deduction REAL DEFAULT 0,
        child_deduction REAL DEFAULT 0,
        insurance_deduction REAL DEFAULT 0,
        provident_fund REAL DEFAULT 0,
        updated_at TEXT DEFAULT (datetime('now'))
    )""")

    # Attendance
    c.execute("""CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        clock_in TEXT,
        clock_out TEXT,
        hours_worked REAL DEFAULT 0,
        ot_hours REAL DEFAULT 0,
        is_late INTEGER DEFAULT 0,
        is_absent INTEGER DEFAULT 0,
        ai_flagged INTEGER DEFAULT 0,
        flag_reason TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(emp_id, work_date)
    )""")

    # Leave Requests
    c.execute("""CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id INTEGER NOT NULL,
        leave_type TEXT NOT NULL,  -- annual | sick | personal
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        days INTEGER NOT NULL,
        reason TEXT,
        status TEXT DEFAULT 'pending',  -- pending | approved | rejected
        approved_by INTEGER,
        decided_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    # Payroll
    c.execute("""CREATE TABLE IF NOT EXISTS payroll (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        status TEXT DEFAULT 'draft',  -- draft | hr_approved | cfo_approved | paid
        total_gross REAL DEFAULT 0,
        total_tax REAL DEFAULT 0,
        total_sso REAL DEFAULT 0,
        total_net REAL DEFAULT 0,
        headcount INTEGER DEFAULT 0,
        ai_flags INTEGER DEFAULT 0,
        approved_by_hr INTEGER,
        approved_by_cfo INTEGER,
        hr_approved_at TEXT,
        cfo_approved_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(month, year)
    )""")

    # Payroll Items (per employee)
    c.execute("""CREATE TABLE IF NOT EXISTS payroll_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payroll_id INTEGER NOT NULL,
        emp_id INTEGER NOT NULL,
        base_salary REAL DEFAULT 0,
        ot_pay REAL DEFAULT 0,
        allowance REAL DEFAULT 0,
        bonus REAL DEFAULT 0,
        commission REAL DEFAULT 0,
        gross REAL DEFAULT 0,
        tax REAL DEFAULT 0,
        sso REAL DEFAULT 0,
        deduction_absent REAL DEFAULT 0,
        net REAL DEFAULT 0,
        prev_net REAL DEFAULT 0,
        change_pct REAL DEFAULT 0,
        ai_flagged INTEGER DEFAULT 0,
        flag_reason TEXT,
        payslip_sent INTEGER DEFAULT 0
    )""")

    # Finance Journal
    c.execute("""CREATE TABLE IF NOT EXISTS finance_journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payroll_id INTEGER NOT NULL,
        entry_type TEXT NOT NULL,   -- salary_expense | wht_payable | sso_payable | net_pay
        account_code TEXT,
        debit REAL DEFAULT 0,
        credit REAL DEFAULT 0,
        description TEXT,
        posted_at TEXT DEFAULT (datetime('now'))
    )""")

    # Tax Documents
    c.execute("""CREATE TABLE IF NOT EXISTS tax_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_type TEXT NOT NULL,   -- PND1 | SSO | PND1KOR
        month INTEGER,
        year INTEGER NOT NULL,
        total_income REAL DEFAULT 0,
        total_tax REAL DEFAULT 0,
        total_sso REAL DEFAULT 0,
        headcount INTEGER DEFAULT 0,
        status TEXT DEFAULT 'draft',  -- draft | submitted
        submitted_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    conn.commit()
    conn.close()

init_db()

# ═══════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)

class LoginRequest(BaseModel):
    username: str
    password: str

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def create_token(user_id: int, db) -> str:
    token = secrets.token_hex(32)
    expires = datetime(2099, 12, 31).isoformat()
    db.execute("INSERT INTO tokens VALUES (?,?,?)", (token, user_id, expires))
    db.commit()
    return token

def fetch_user_by_token(token: str, db):
    row = db.execute(
        "SELECT t.user_id, u.role, u.username, u.emp_id FROM tokens t JOIN users u ON t.user_id=u.id WHERE t.token=?",
        (token,),
    ).fetchone()
    return dict(row) if row else None

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db=Depends(get_db)):
    user = fetch_user_by_token(credentials.credentials, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user

def require_role(*roles):
    def checker(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail=f"Required role: {roles}")
        return user
    return checker

@app.post("/auth/register", tags=["Auth"], summary="สร้าง User ใหม่")
def register(
    req: LoginRequest,
    role: str = "hr_admin",
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db=Depends(get_db),
):
    has_any_user = db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    if has_any_user:
        if not credentials:
            raise HTTPException(status_code=401, detail="Authentication required")
        user = fetch_user_by_token(credentials.credentials, db)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        if user["role"] != "hr_admin":
            raise HTTPException(status_code=403, detail="Required role: ('hr_admin',)")
    try:
        db.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                   (req.username, hash_password(req.password), role))
        db.commit()
        return {"message": f"User '{req.username}' created with role '{role}'"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")

@app.post("/auth/login", tags=["Auth"], summary="Login รับ Token")
def login(req: LoginRequest, db=Depends(get_db)):
    row = db.execute("SELECT * FROM users WHERE username=? AND password_hash=?",
                     (req.username, hash_password(req.password))).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(row["id"], db)
    return {"access_token": token, "token_type": "bearer", "role": row["role"]}

@app.get("/auth/me", tags=["Auth"], summary="ดู Profile ตัวเอง")
def me(user=Depends(get_current_user)):
    return user

# ═══════════════════════════════════════════
# PHASE 1: ONBOARDING
# ═══════════════════════════════════════════

class EmployeeCreate(BaseModel):
    name: str
    department: str
    title: str
    start_date: str
    salary: float = Field(gt=0)
    employment_type: str = "full-time"
    bank_account: str
    bank_name: str = "SCB"
    manager_id: Optional[int] = None

@app.post("/employees", tags=["Phase 1: Onboarding"], summary="เพิ่มพนักงานใหม่ + Code Bot กระจายข้อมูล", status_code=201)
def create_employee(body: EmployeeCreate, user=Depends(require_role("hr_admin")), db=Depends(get_db)):
    quota = (10, 30, 3) if body.employment_type == "full-time" else (5, 15, 1)
    emp_id = bootstrap_new_employee(
        db,
        body.name,
        body.department,
        body.title,
        body.start_date,
        body.salary,
        body.employment_type,
        body.bank_account,
        body.bank_name,
        body.manager_id,
    )
    db.commit()

    outs = emit(
        "employee.created",
        emp_id=emp_id,
        employment_type=body.employment_type,
        manager_id=body.manager_id,
    )
    merged = outs[0] if outs else {}

    return {
        "message": "✅ Onboarding สำเร็จ",
        "emp_id": emp_id,
        "code_bot_actions": merged.get(
            "actions",
            [
                f"สร้าง Employee Profile (id={emp_id})",
                f"ตั้งค่า Leave Quota: annual={quota[0]}, sick={quota[1]}, personal={quota[2]} วัน",
                "สร้าง Tax Profile เริ่มต้น",
                f"แจ้งเตือน Manager (id={body.manager_id}) [simulated]",
            ],
        ),
        "onboarding_event": merged,
    }

@app.get("/employees", tags=["Phase 1: Onboarding"], summary="ดูรายชื่อพนักงานทั้งหมด")
def list_employees(db=Depends(get_db), user=Depends(get_current_user)):
    rows = db.execute("SELECT * FROM employees WHERE status='active'").fetchall()
    return [dict(r) for r in rows]

@app.get("/employees/{emp_id}", tags=["Phase 1: Onboarding"], summary="ดูข้อมูลพนักงานรายคน")
def get_employee(emp_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = db.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Employee not found")
    quota = db.execute("SELECT * FROM leave_quota WHERE emp_id=? AND year=?", (emp_id, datetime.now().year)).fetchone()
    tax = db.execute("SELECT * FROM tax_profiles WHERE emp_id=?", (emp_id,)).fetchone()
    return {"employee": dict(row), "leave_quota": dict(quota) if quota else None, "tax_profile": dict(tax) if tax else None}

# ═══════════════════════════════════════════
# PHASE 2: ATTENDANCE & LEAVE
# ═══════════════════════════════════════════

class ClockOutRequest(BaseModel):
    emp_id: int
    clock_in: str   # ISO datetime
    clock_out: str
    work_date: Optional[str] = None

class LeaveRequest(BaseModel):
    emp_id: int
    leave_type: str  # annual | sick | personal
    start_date: str
    end_date: str
    days: int
    reason: Optional[str] = None

class LeaveDecision(BaseModel):
    approved: bool
    note: Optional[str] = None

@app.post("/attendance/clock_out", tags=["Phase 2: Attendance"], summary="บันทึกเวลา + Code Bot คำนวณ OT")
def clock_out(body: ClockOutRequest, db=Depends(get_db), user=Depends(get_current_user)):
    try:
        return insert_attendance_safe(
            db,
            body.emp_id,
            body.clock_in,
            body.clock_out,
            body.work_date,
            DEFAULT_POLICY,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

@app.get("/attendance/{emp_id}", tags=["Phase 2: Attendance"], summary="ดูประวัติเวลาทำงาน")
def get_attendance(emp_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    rows = db.execute("SELECT * FROM attendance WHERE emp_id=? ORDER BY work_date DESC LIMIT 30", (emp_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/leave", tags=["Phase 2: Leave"], summary="ยื่นใบลา", status_code=201)
def create_leave(body: LeaveRequest, db=Depends(get_db), user=Depends(get_current_user)):
    year = datetime.now().year
    quota = db.execute("SELECT * FROM leave_quota WHERE emp_id=? AND year=?", (body.emp_id, year)).fetchone()
    if not quota:
        raise HTTPException(404, "Leave quota not found")

    # Code Bot: ตรวจสิทธิ์วันลา
    used_col = f"{body.leave_type}_used"
    total_col = f"{body.leave_type}_total"
    if dict(quota).get(used_col, 0) + body.days > dict(quota).get(total_col, 0):
        raise HTTPException(400, f"วันลาไม่พอ: ใช้ไปแล้ว {dict(quota)[used_col]} วัน จากสิทธิ์ {dict(quota)[total_col]} วัน")

    cur = db.execute("""INSERT INTO leave_requests (emp_id,leave_type,start_date,end_date,days,reason)
                        VALUES (?,?,?,?,?,?)""",
                     (body.emp_id, body.leave_type, body.start_date, body.end_date, body.days, body.reason))
    db.commit()
    return {"message": "✅ ยื่นใบลาสำเร็จ รอ Manager อนุมัติ", "leave_id": cur.lastrowid}

@app.post("/leave/{leave_id}/decision", tags=["Phase 2: Leave"], summary="✋ Manager อนุมัติ/ปฏิเสธใบลา [Human Checkpoint]")
def decide_leave(leave_id: int, body: LeaveDecision, user=Depends(require_role("manager","cfo","hr_admin")), db=Depends(get_db)):
    leave = db.execute("SELECT * FROM leave_requests WHERE id=?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Leave request not found")
    if dict(leave)["status"] != "pending":
        raise HTTPException(400, "Leave already decided")

    if body.approved:
        try:
            r = update_leave_after_approval(db, leave_id, user["user_id"])
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {
            "message": "✅ อนุมัติใบลาแล้ว",
            "leave_id": leave_id,
            "status": "approved",
            "decided_by": user["username"],
            **r,
        }

    db.execute(
        "UPDATE leave_requests SET status=?, approved_by=?, decided_at=? WHERE id=?",
        ("rejected", user["user_id"], datetime.now().isoformat(), leave_id),
    )
    db.commit()
    return {
        "message": "❌ ปฏิเสธใบลาแล้ว",
        "leave_id": leave_id,
        "status": "rejected",
        "decided_by": user["username"],
        "code_bot_actions": ["แจ้งพนักงาน [simulated]"],
    }

@app.get("/leave/pending/all", tags=["Phase 2: Leave"], summary="ดูใบลาที่รอ Approve ทั้งหมด")
def pending_leaves(db=Depends(get_db), user=Depends(require_role("manager","cfo","hr_admin"))):
    rows = db.execute("""SELECT lr.*, e.name as emp_name FROM leave_requests lr
                         JOIN employees e ON lr.emp_id=e.id WHERE lr.status='pending'""").fetchall()
    return [dict(r) for r in rows]

# ═══════════════════════════════════════════
# PHASE 3: PAYROLL
# ═══════════════════════════════════════════

@app.post("/payroll/run", tags=["Phase 3: Payroll"], summary="Code Bot คำนวณ Payroll ทุกคน + AI Flag")
def run_payroll(month: int = None, year: int = None, user=Depends(require_role("hr_admin")), db=Depends(get_db)):
    now = datetime.now()
    month = month or now.month
    year = year or now.year
    try:
        return run_payroll_batch(db, month, year)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

@app.post("/payroll/{payroll_id}/hr_approve", tags=["Phase 3: Payroll"], summary="✋ HR Admin ตรวจสอบ Payroll [Human Checkpoint 1]")
def hr_approve_payroll(payroll_id: int, user=Depends(require_role("hr_admin")), db=Depends(get_db)):
    p = db.execute("SELECT * FROM payroll WHERE id=?", (payroll_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Payroll not found")
    if dict(p)["status"] != "draft":
        raise HTTPException(400, f"Payroll status: {dict(p)['status']} (ต้องเป็น draft)")
    db.execute("UPDATE payroll SET status='hr_approved', approved_by_hr=?, hr_approved_at=? WHERE id=?",
               (user["user_id"], datetime.now().isoformat(), payroll_id))
    db.commit()
    return {"message": "✅ HR อนุมัติ Payroll แล้ว", "next_step": "POST /payroll/{id}/cfo_approve → CFO อนุมัติขั้นสุดท้าย"}

@app.post("/payroll/{payroll_id}/cfo_approve", tags=["Phase 3: Payroll"], summary="✋ CFO อนุมัติ Payroll ขั้นสุดท้าย [Human Checkpoint 2]")
def cfo_approve_payroll(payroll_id: int, user=Depends(require_role("cfo","hr_admin")), db=Depends(get_db)):
    p = db.execute("SELECT * FROM payroll WHERE id=?", (payroll_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Payroll not found")
    if dict(p)["status"] != "hr_approved":
        raise HTTPException(400, f"Payroll status: {dict(p)['status']} (ต้องผ่าน HR ก่อน)")
    db.execute("UPDATE payroll SET status='cfo_approved', approved_by_cfo=?, cfo_approved_at=? WHERE id=?",
               (user["user_id"], datetime.now().isoformat(), payroll_id))
    db.commit()
    return {"message": "✅ CFO อนุมัติ Payroll แล้ว", "next_step": "POST /payment/dispatch?payroll_id={id} → โอนเงิน"}

@app.get("/payroll/{payroll_id}", tags=["Phase 3: Payroll"], summary="ดูรายละเอียด Payroll")
def get_payroll(payroll_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    p = db.execute("SELECT * FROM payroll WHERE id=?", (payroll_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Payroll not found")
    items = db.execute("""SELECT pi.*, e.name, e.department FROM payroll_items pi
                          JOIN employees e ON pi.emp_id=e.id WHERE pi.payroll_id=?""", (payroll_id,)).fetchall()
    return {"payroll": dict(p), "items": [dict(i) for i in items]}

# ═══════════════════════════════════════════
# PHASE 4: PAYMENT
# ═══════════════════════════════════════════

@app.post("/payment/dispatch", tags=["Phase 4: Payment"], summary="Code Bot โอนเงิน + ส่ง Payslip + Post Finance GL")
def dispatch_payment(payroll_id: int, user=Depends(require_role("cfo","hr_admin")), db=Depends(get_db)):
    p = db.execute("SELECT * FROM payroll WHERE id=?", (payroll_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Payroll not found")
    # Concurrency-safe claim: only one request can move cfo_approved -> payment_processing
    claimed = db.execute(
        "UPDATE payroll SET status='payment_processing' WHERE id=? AND status='cfo_approved'",
        (payroll_id,),
    ).rowcount
    db.commit()
    if claimed == 0:
        latest = db.execute("SELECT status FROM payroll WHERE id=?", (payroll_id,)).fetchone()
        current = dict(latest)["status"] if latest else "unknown"
        raise HTTPException(400, f"Payroll status: {current} (ต้องเป็น cfo_approved)")

    try:
        result = dispatch_payment_for_payroll(db, payroll_id)
    except Exception as e:
        # Roll back state for retry if dispatch fails mid-flight.
        db.execute("UPDATE payroll SET status='cfo_approved' WHERE id=? AND status='payment_processing'", (payroll_id,))
        db.commit()
        raise HTTPException(500, f"Payment dispatch failed: {e}") from e

    bf = result.get("bank_files_created") or {}
    bank_summary = {k: v.get("lines") if isinstance(v, dict) else v for k, v in bf.items()}
    return {
        "message": "✅ Payment Dispatched สำเร็จ",
        "payroll_id": payroll_id,
        "code_bot_actions": {
            "bank_files_created": bank_summary or bf,
            "payslips_sent": result.get("payslips_sent"),
            "finance_journal_entries": result.get("finance_journal_entries"),
            "gl_accounts_posted": ["5100 Salary Expense", "2100 Net Pay", "2200 WHT Payable", "2300 SSO Payable"],
        },
        "dispatcher_detail": result,
    }

@app.get("/finance/journal", tags=["Phase 4: Payment"], summary="ดู Finance Journal Entries")
def get_journal(db=Depends(get_db), user=Depends(require_role("cfo","hr_admin"))):
    rows = db.execute("SELECT * FROM finance_journal ORDER BY posted_at DESC").fetchall()
    return [dict(r) for r in rows]

# ═══════════════════════════════════════════
# PHASE 5: TAX & SSO
# ═══════════════════════════════════════════

@app.post("/tax/generate", tags=["Phase 5: Tax & SSO"], summary="Code Bot สร้างเอกสารภาษี ภ.ง.ด.1 + สปส.")
def generate_tax(month: int, year: int, user=Depends(require_role("hr_admin")), db=Depends(get_db)):
    try:
        out = generate_tax_documents(db, month, year)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"message": "✅ สร้างเอกสารภาษีสำเร็จ", **out}

@app.post("/tax/{doc_id}/submit", tags=["Phase 5: Tax & SSO"], summary="✋ HR ยืนยันยื่นเอกสารแล้ว [Human Checkpoint]")
def submit_tax(doc_id: int, user=Depends(require_role("hr_admin")), db=Depends(get_db)):
    doc = db.execute("SELECT * FROM tax_documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        raise HTTPException(404, "Document not found")
    db.execute("UPDATE tax_documents SET status='submitted', submitted_at=? WHERE id=?",
               (datetime.now().isoformat(), doc_id))
    db.commit()
    return {"message": f"✅ ยืนยันยื่นเอกสาร {dict(doc)['doc_type']} แล้ว", "submitted_at": datetime.now().isoformat()}

# ═══════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════

@app.get("/dashboard/summary", tags=["Dashboard"], summary="สรุปภาพรวมระบบ HR")
def dashboard(db=Depends(get_db), user=Depends(get_current_user)):
    emp_count = db.execute("SELECT COUNT(*) as c FROM employees WHERE status='active'").fetchone()["c"]
    pending_leave = db.execute("SELECT COUNT(*) as c FROM leave_requests WHERE status='pending'").fetchone()["c"]
    latest_payroll = db.execute("SELECT * FROM payroll ORDER BY year DESC, month DESC LIMIT 1").fetchone()
    flagged_att = db.execute("SELECT COUNT(*) as c FROM attendance WHERE ai_flagged=1").fetchone()["c"]
    pending_tax = db.execute("SELECT COUNT(*) as c FROM tax_documents WHERE status='draft'").fetchone()["c"]

    return {
        "employees": {"active": emp_count},
        "attendance": {"ai_flagged_total": flagged_att},
        "leave": {"pending_approval": pending_leave},
        "payroll": dict(latest_payroll) if latest_payroll else None,
        "tax_documents": {"pending_submission": pending_tax},
        "ai_insight": f"มีใบลารอ Approve {pending_leave} ใบ | เอกสารภาษีรอยื่น {pending_tax} ฉบับ"
    }

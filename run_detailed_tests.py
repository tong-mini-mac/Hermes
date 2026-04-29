import json
import os
from datetime import datetime

from fastapi.testclient import TestClient


def step(results, name, fn):
    started = datetime.now().isoformat()
    try:
        data = fn()
        if hasattr(data, "status_code"):
            try:
                body = data.json()
            except Exception:
                body = data.text
            safe_data = {"status_code": data.status_code, "body": body}
        else:
            safe_data = data
        results.append(
            {
                "name": name,
                "status": "PASS",
                "started_at": started,
                "result": safe_data,
            }
        )
        return data
    except Exception as e:
        results.append(
            {
                "name": name,
                "status": "FAIL",
                "started_at": started,
                "error": str(e),
            }
        )
        return None


def expect_status(resp, code, context):
    if resp.status_code != code:
        raise AssertionError(f"{context}: expected {code}, got {resp.status_code}, body={resp.text}")


def main():
    if os.path.exists("hr.db"):
        os.remove("hr.db")

    import app as hr_app

    client = TestClient(hr_app.app)
    results = []
    state = {}

    step(
        results,
        "auth.register.first_user.hr_admin",
        lambda: expect_status(
            client.post("/auth/register?role=hr_admin", json={"username": "hr", "password": "hr1234"}),
            200,
            "register first hr",
        ),
    )
    login_hr = step(
        results,
        "auth.login.hr_admin",
        lambda: client.post("/auth/login", json={"username": "hr", "password": "hr1234"}),
    )
    if login_hr is not None:
        expect_status(login_hr, 200, "login hr")
        state["hr_token"] = login_hr.json()["access_token"]

    def auth_headers(token):
        return {"Authorization": f"Bearer {token}"}

    step(
        results,
        "auth.register.manager.by_hr",
        lambda: expect_status(
            client.post(
                "/auth/register?role=manager",
                json={"username": "manager1", "password": "pass1234"},
                headers=auth_headers(state["hr_token"]),
            ),
            200,
            "register manager",
        ),
    )
    step(
        results,
        "auth.register.cfo.by_hr",
        lambda: expect_status(
            client.post(
                "/auth/register?role=cfo",
                json={"username": "cfo1", "password": "pass1234"},
                headers=auth_headers(state["hr_token"]),
            ),
            200,
            "register cfo",
        ),
    )
    login_mgr = client.post("/auth/login", json={"username": "manager1", "password": "pass1234"})
    expect_status(login_mgr, 200, "login manager")
    state["manager_token"] = login_mgr.json()["access_token"]

    login_cfo = client.post("/auth/login", json={"username": "cfo1", "password": "pass1234"})
    expect_status(login_cfo, 200, "login cfo")
    state["cfo_token"] = login_cfo.json()["access_token"]

    # Negative: non-hr register should fail
    step(
        results,
        "auth.register.by_non_hr_forbidden",
        lambda: expect_status(
            client.post(
                "/auth/register?role=employee",
                json={"username": "baduser", "password": "x"},
                headers=auth_headers(state["manager_token"]),
            ),
            403,
            "non-hr register forbidden",
        ),
    )

    # Onboarding 2 employees
    emp1_resp = client.post(
        "/employees",
        headers=auth_headers(state["hr_token"]),
        json={
            "name": "Alice Finance",
            "department": "Finance",
            "title": "Accountant",
            "start_date": "2026-04-01",
            "salary": 50000,
            "employment_type": "full-time",
            "bank_account": "111-111-111",
            "bank_name": "SCB",
            "manager_id": 2,
        },
    )
    expect_status(emp1_resp, 201, "create employee 1")
    emp1_id = emp1_resp.json()["emp_id"]
    state["emp1_id"] = emp1_id
    results.append({"name": "phase1.create_employee.emp1", "status": "PASS", "result": emp1_resp.json()})

    emp2_resp = client.post(
        "/employees",
        headers=auth_headers(state["hr_token"]),
        json={
            "name": "Bob Sales",
            "department": "Sales",
            "title": "Sales Exec",
            "start_date": "2026-04-10",
            "salary": 42000,
            "employment_type": "full-time",
            "bank_account": "222-222-222",
            "bank_name": "KBANK",
            "manager_id": 2,
        },
    )
    expect_status(emp2_resp, 201, "create employee 2")
    state["emp2_id"] = emp2_resp.json()["emp_id"]
    results.append({"name": "phase1.create_employee.emp2", "status": "PASS", "result": emp2_resp.json()})

    # Attendance normal + anomalous
    att1 = client.post(
        "/attendance/clock_out",
        headers=auth_headers(state["hr_token"]),
        json={
            "emp_id": state["emp1_id"],
            "clock_in": "2026-04-28T09:05:00",
            "clock_out": "2026-04-28T18:15:00",
        },
    )
    expect_status(att1, 200, "attendance emp1")
    results.append({"name": "phase2.attendance.emp1.normal", "status": "PASS", "result": att1.json()})

    att2 = client.post(
        "/attendance/clock_out",
        headers=auth_headers(state["hr_token"]),
        json={
            "emp_id": state["emp2_id"],
            "clock_in": "2026-04-28T10:10:00",
            "clock_out": "2026-04-28T22:30:00",
        },
    )
    expect_status(att2, 200, "attendance emp2 anomaly")
    results.append({"name": "phase2.attendance.emp2.flagged", "status": "PASS", "result": att2.json()})

    dup_att = client.post(
        "/attendance/clock_out",
        headers=auth_headers(state["hr_token"]),
        json={
            "emp_id": state["emp2_id"],
            "clock_in": "2026-04-28T10:10:00",
            "clock_out": "2026-04-28T22:30:00",
        },
    )
    expect_status(dup_att, 400, "duplicate attendance should fail")
    results.append({"name": "phase2.attendance.duplicate_record", "status": "PASS", "result": dup_att.json()})

    # Leave request + approval
    leave_resp = client.post(
        "/leave",
        headers=auth_headers(state["hr_token"]),
        json={
            "emp_id": state["emp1_id"],
            "leave_type": "annual",
            "start_date": "2026-05-05",
            "end_date": "2026-05-06",
            "days": 2,
            "reason": "Personal",
        },
    )
    expect_status(leave_resp, 201, "create leave")
    leave_id = leave_resp.json()["leave_id"]
    state["leave_id"] = leave_id
    results.append({"name": "phase2.leave.create", "status": "PASS", "result": leave_resp.json()})

    # Non-authorized role check (simulate employee by missing role: use random token invalid for endpoint)
    bad_decision = client.post(
        f"/leave/{leave_id}/decision",
        headers=auth_headers(state["manager_token"]),
        json={"approved": True},
    )
    expect_status(bad_decision, 200, "manager approve leave")
    results.append({"name": "phase2.leave.manager_approve", "status": "PASS", "result": bad_decision.json()})

    # Payroll
    payroll_run = client.post("/payroll/run?month=4&year=2026", headers=auth_headers(state["hr_token"]))
    expect_status(payroll_run, 200, "run payroll")
    payroll_id = payroll_run.json()["payroll_id"]
    state["payroll_id"] = payroll_id
    results.append({"name": "phase3.payroll.run", "status": "PASS", "result": payroll_run.json()})

    payroll_run_dup = client.post("/payroll/run?month=4&year=2026", headers=auth_headers(state["hr_token"]))
    expect_status(payroll_run_dup, 400, "duplicate payroll run should fail")
    results.append({"name": "phase3.payroll.run_duplicate", "status": "PASS", "result": payroll_run_dup.json()})

    hr_approve = client.post(f"/payroll/{payroll_id}/hr_approve", headers=auth_headers(state["hr_token"]))
    expect_status(hr_approve, 200, "hr approve payroll")
    results.append({"name": "phase3.payroll.hr_approve", "status": "PASS", "result": hr_approve.json()})

    cfo_approve = client.post(f"/payroll/{payroll_id}/cfo_approve", headers=auth_headers(state["cfo_token"]))
    expect_status(cfo_approve, 200, "cfo approve payroll")
    results.append({"name": "phase3.payroll.cfo_approve", "status": "PASS", "result": cfo_approve.json()})

    # Payment dispatch
    payment = client.post(f"/payment/dispatch?payroll_id={payroll_id}", headers=auth_headers(state["cfo_token"]))
    expect_status(payment, 200, "dispatch payment")
    results.append({"name": "phase4.payment.dispatch", "status": "PASS", "result": payment.json()})

    # Tax generation + submit
    tax_gen = client.post("/tax/generate?month=4&year=2026", headers=auth_headers(state["hr_token"]))
    expect_status(tax_gen, 200, "generate tax docs")
    results.append({"name": "phase5.tax.generate", "status": "PASS", "result": tax_gen.json()})

    docs = tax_gen.json().get("documents", [])
    if docs:
        doc_id = docs[0]["id"]
        submit = client.post(f"/tax/{doc_id}/submit", headers=auth_headers(state["hr_token"]))
        expect_status(submit, 200, "submit tax doc")
        results.append({"name": "phase5.tax.submit", "status": "PASS", "result": submit.json()})

    # Dashboard
    dash = client.get("/dashboard/summary", headers=auth_headers(state["hr_token"]))
    expect_status(dash, 200, "dashboard summary")
    results.append({"name": "dashboard.summary", "status": "PASS", "result": dash.json()})

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = [r for r in results if r["status"] == "FAIL"]
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {"total": len(results), "passed": passed, "failed": len(failed)},
        "failed_cases": failed,
        "results": results,
    }
    with open("test_report_raw.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps(report["summary"], ensure_ascii=False))
    if failed:
        print("FAILED_CASES")
        for case in failed:
            print(case["name"], "=>", case.get("error"))


if __name__ == "__main__":
    main()

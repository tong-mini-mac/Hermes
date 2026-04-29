import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from fastapi.testclient import TestClient


def expect(resp, code, ctx):
    if resp.status_code != code:
        raise AssertionError(f"{ctx}: expected={code} got={resp.status_code} body={resp.text}")


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def setup_base(client):
    expect(client.post("/auth/register?role=hr_admin", json={"username": "hr", "password": "hr1234"}), 200, "register hr")
    hr = client.post("/auth/login", json={"username": "hr", "password": "hr1234"})
    expect(hr, 200, "login hr")
    hr_token = hr.json()["access_token"]

    expect(
        client.post(
            "/auth/register?role=cfo",
            json={"username": "cfo1", "password": "pass1234"},
            headers=headers(hr_token),
        ),
        200,
        "register cfo",
    )
    cfo = client.post("/auth/login", json={"username": "cfo1", "password": "pass1234"})
    expect(cfo, 200, "login cfo")
    cfo_token = cfo.json()["access_token"]

    e1 = client.post(
        "/employees",
        headers=headers(hr_token),
        json={
            "name": "Year End A",
            "department": "Finance",
            "title": "Accountant",
            "start_date": "2026-01-01",
            "salary": 50000,
            "employment_type": "full-time",
            "bank_account": "111",
            "bank_name": "SCB",
            "manager_id": None,
        },
    )
    expect(e1, 201, "create emp1")
    e2 = client.post(
        "/employees",
        headers=headers(hr_token),
        json={
            "name": "Year End B",
            "department": "Sales",
            "title": "Sales",
            "start_date": "2026-01-01",
            "salary": 42000,
            "employment_type": "full-time",
            "bank_account": "222",
            "bank_name": "KBANK",
            "manager_id": None,
        },
    )
    expect(e2, 201, "create emp2")
    return hr_token, cfo_token, e1.json()["emp_id"], e2.json()["emp_id"]


def test_year_end(client, hr_token, cfo_token):
    # Attendance in Dec to produce OT component
    expect(
        client.post(
            "/attendance/clock_out",
            headers=headers(hr_token),
            json={"emp_id": 1, "clock_in": "2026-12-28T09:00:00", "clock_out": "2026-12-28T20:00:00"},
        ),
        200,
        "attendance dec",
    )
    # Payroll month 12
    run = client.post("/payroll/run?month=12&year=2026", headers=headers(hr_token))
    expect(run, 200, "payroll run dec")
    payroll_id = run.json()["payroll_id"]
    expect(client.post(f"/payroll/{payroll_id}/hr_approve", headers=headers(hr_token)), 200, "hr approve dec")
    expect(client.post(f"/payroll/{payroll_id}/cfo_approve", headers=headers(cfo_token)), 200, "cfo approve dec")
    expect(client.post(f"/payment/dispatch?payroll_id={payroll_id}", headers=headers(cfo_token)), 200, "pay dec")

    tax = client.post("/tax/generate?month=12&year=2026", headers=headers(hr_token))
    expect(tax, 200, "tax generate dec")
    docs = tax.json().get("documents", [])
    has_pnd1kor = any(d.get("type", "").startswith("ภ.ง.ด.1ก") for d in docs)
    if not has_pnd1kor:
        raise AssertionError(f"year-end tax docs missing PND1KOR; docs={docs}")
    return {"status": "PASS", "payroll_id": payroll_id, "documents": docs}


def test_concurrency_duplicate_attendance(app_module, hr_token):
    """Concurrent writes on unique(emp_id, work_date): should allow exactly one success."""

    def hit_once():
        with TestClient(app_module.app) as local_client:
            return local_client.post(
                "/attendance/clock_out",
                headers=headers(hr_token),
                json={
                    "emp_id": 2,
                    "clock_in": "2026-12-29T09:30:00",
                    "clock_out": "2026-12-29T19:00:00",
                    "work_date": "2026-12-29",
                },
            )

    responses = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(hit_once) for _ in range(8)]
        for f in as_completed(futs):
            responses.append(f.result())

    codes = [r.status_code for r in responses]
    ok_count = sum(1 for c in codes if c == 200)
    dup_count = sum(1 for c in codes if c == 400)
    if ok_count != 1 or dup_count != 7:
        bodies = [r.text for r in responses]
        raise AssertionError(f"unexpected concurrency outcome codes={codes} bodies={bodies}")
    return {"status": "PASS", "codes": codes}


def test_concurrency_payment_dispatch(app_module, cfo_token, payroll_id):
    """
    Concurrent dispatch attempts on same payroll should be idempotent.
    Current expected production-safe behavior: 1 success, remaining should reject.
    """

    def hit_once():
        with TestClient(app_module.app) as local_client:
            return local_client.post(f"/payment/dispatch?payroll_id={payroll_id}", headers=headers(cfo_token))

    responses = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(hit_once) for _ in range(5)]
        for f in as_completed(futs):
            responses.append(f.result())
    codes = [r.status_code for r in responses]
    success = sum(1 for c in codes if c == 200)
    rejected = sum(1 for c in codes if c == 400)
    # We accept either fully serialized (1 success + 4 reject) or unsafe multiple 200s (fail).
    if success != 1 or rejected != 4:
        bodies = [r.text for r in responses]
        raise AssertionError(f"dispatch not idempotent under concurrency codes={codes} bodies={bodies}")
    return {"status": "PASS", "codes": codes}


def main():
    if os.path.exists("hr.db"):
        os.remove("hr.db")
    import app as app_module

    out = {"timestamp": datetime.now().isoformat(), "results": []}
    with TestClient(app_module.app) as client:
        hr_token, cfo_token, _, _ = setup_base(client)
        year_end_result = test_year_end(client, hr_token, cfo_token)
        out["results"].append({"name": "year_end_pnd1kor", **year_end_result})

        att_concurrency = test_concurrency_duplicate_attendance(app_module, hr_token)
        out["results"].append({"name": "concurrency_duplicate_attendance", **att_concurrency})

        # Create another payroll for concurrency dispatch test
        expect(client.post("/payroll/run?month=11&year=2026", headers=headers(hr_token)), 200, "payroll nov")
        payroll_id = client.post("/payroll/run?month=10&year=2026", headers=headers(hr_token))
        # month 10 may not exist, this gives deterministic new payroll for dispatch race
        if payroll_id.status_code == 400:
            # fallback create month 9
            payroll_id = client.post("/payroll/run?month=9&year=2026", headers=headers(hr_token))
        expect(payroll_id, 200, "create payroll for dispatch race")
        pid = payroll_id.json()["payroll_id"]
        expect(client.post(f"/payroll/{pid}/hr_approve", headers=headers(hr_token)), 200, "hr approve race payroll")
        expect(client.post(f"/payroll/{pid}/cfo_approve", headers=headers(cfo_token)), 200, "cfo approve race payroll")

        dispatch_concurrency = test_concurrency_payment_dispatch(app_module, cfo_token, pid)
        out["results"].append({"name": "concurrency_payment_dispatch", **dispatch_concurrency})

    out["summary"] = {
        "total": len(out["results"]),
        "passed": sum(1 for r in out["results"] if r.get("status") == "PASS"),
        "failed": sum(1 for r in out["results"] if r.get("status") != "PASS"),
    }
    with open("production_gap_report.json", "w", encoding="utf-8") as f:
        import json

        json.dump(out, f, ensure_ascii=False, indent=2)
    print(out["summary"])


if __name__ == "__main__":
    main()

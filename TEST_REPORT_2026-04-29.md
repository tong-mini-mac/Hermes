# Test Report — HR Automation API

Test date: 2026-04-29  
Method: End-to-end API testing with `fastapi.testclient` via `run_detailed_tests.py`  
Raw results: `test_report_raw.json`

## 1) Scope

Covers all workflow phases:

1. Auth (register/login/role enforcement)
2. Onboarding (`POST /employees`)
3. Attendance (`POST /attendance/clock_out`)
4. Leave (`POST /leave`, `POST /leave/{id}/decision`)
5. Payroll (`POST /payroll/run`, HR approve, CFO approve)
6. Payment dispatch (`POST /payment/dispatch`)
7. Tax/SSO (`POST /tax/generate`, `POST /tax/{id}/submit`)
8. Dashboard (`GET /dashboard/summary`)

Includes both positive and negative test cases.

## 2) Summary

- Total cases: **20**
- Passed: **20**
- Failed: **0**
- Overall status: **PASS**

## 3) Test Matrix (Key Points)

- Auth
  - First user registration (without token): PASS
  - Login hr/manager/cfo: PASS
  - Manager tries to register a new user (must be denied): PASS (403)
- Onboarding
  - Create 2 employees + event `employee.created`: PASS
  - Verify `code_bot_actions` and onboarding event output: PASS
- Attendance
  - Record attendance for emp1: PASS
  - Record attendance for emp2 with OT policy flag: PASS
  - Duplicate same-day attendance insert: PASS (400 expected)
- Leave
  - Submit leave request: PASS
  - Manager approves leave + quota update flow: PASS
- Payroll
  - Run payroll for 4/2026: PASS
  - Run duplicate payroll for same month: PASS (400 expected)
  - HR approve: PASS
  - CFO approve: PASS
- Payment
  - Dispatch payment after CFO approval: PASS
  - Verify bank summary + payslip count + finance journal count: PASS
- Tax/SSO
  - Generate docs (PND1 + SSO): PASS
  - Submit tax document: PASS
- Dashboard
  - Summary reflects payroll/tax/attendance state correctly: PASS

## 4) Issues and Obstacles Found

### Issue #1: TestClient failed due to missing `httpx`

- Symptom:
  - `RuntimeError: The starlette.testclient module requires the httpx package`
- Root cause:
  - environment missing `httpx`
- Fix:
  - install `httpx` (`pip install httpx`)
  - add `httpx>=0.28.0` to `requirements.txt`
- Result:
  - test script runs successfully

### Issue #2: JSON report serialization error

- Symptom:
  - `TypeError: Object of type Response is not JSON serializable`
- Root cause:
  - `Response` object stored directly in report payload
- Fix:
  - normalize to serializable data (`status_code`, `json/text`) before writing
- Result:
  - `test_report_raw.json` generated successfully

## 5) Behavioral Observations

- Attendance for emp1 (clock-in 09:05) is marked `is_late=true` and `ai_flagged=true` per current policy (start time 09:00, no grace period).
- First payroll month anomaly is not flagged when `prev_net=0` (intended behavior).
- Tax generation after payment works correctly and creates expected documents.

## 6) Remaining Risks / Gaps to Test

- Leave-type edge cases outside allowed values (`annual/sick/personal`)
- Additional role tests for restricted endpoints with employee role
- Year-end case for `PND1KOR` (month 12)
- Data-volume/load tests (thousands of employees)
- Concurrency tests (simultaneous approve/payment requests)

## 7) Artifacts

- Test script: `run_detailed_tests.py`
- Raw result: `test_report_raw.json`
- This report: `TEST_REPORT_2026-04-29.md`

# HR Multi-Country Refactor Checklist

Goal: clearly separate the system into `Universal Core` and `Thailand Plugin` so new countries can be added without changing core logic.

## Target Architecture

- `core/` = shared across all countries
- `plugins/th/` = Thailand tax/social-security/bank/deadline rules
- call through interfaces only (`TaxProvider`, `ComplianceProvider`, `BankFormatProvider`)

## Phase 0 — Baseline & Safety

- [ ] Freeze current schema + endpoint behavior
- [ ] Export sample test data (`employees`, `attendance`, `payroll`, `tax_documents`)
- [ ] Add minimum regression tests:
- [ ] Onboarding flow
- [ ] Attendance + leave approve
- [ ] Payroll run + 2-step approval
- [ ] Payment dispatch
- [ ] Tax generation/submission

## Phase 1 — Create Universal Interfaces

- [ ] Create `core/contracts/`:
- [ ] `tax_provider.py`
- [ ] `compliance_provider.py`
- [ ] `bank_format_provider.py`
- [ ] Define core methods:
- [ ] `calculate_tax(gross, context)`
- [ ] `calculate_social_security(gross, context)`
- [ ] `generate_monthly_documents(payroll_batch)`
- [ ] `generate_annual_documents(year)`
- [ ] `build_transfer_file(bank_code, records)`

## Phase 2 — Move Universal Logic to Core

- [ ] Move logic into `core/`:
- [ ] Event bus (`on_event`, `emit`)
- [ ] Attendance engine (clock-in/out, OT calc framework)
- [ ] Leave workflow (request/approve/reject state)
- [ ] Payroll aggregator (base + ot + commission + bonus + allowance)
- [ ] AI flag framework (MoM jump, anomaly channel)
- [ ] Notification channel (email/sms/in-app interface)
- [ ] Finance GL posting framework

## Phase 3 — Build Thailand Plugin

- [ ] Create `plugins/th/`:
- [ ] `tax_th.py` (progressive tax + deduction rules)
- [ ] `sso_th.py` (5% + legal cap for Thailand)
- [ ] `compliance_th.py` (PND1, SSO 1-10, PND1KOR)
- [ ] `banks_th.py` (SCB, KBANK, BBL format adapters)
- [ ] `deadlines_th.py` (day 7 / day 15 rules)
- [ ] `integrations/prism.py`

## Phase 4 — Wire Plugin Loader

- [ ] Create `core/plugins/loader.py`
- [ ] Support config:
- [ ] `COUNTRY=TH`
- [ ] `BANK_PROFILE=TH_DEFAULT`
- [ ] Bind providers at startup:
- [ ] `TaxProvider <- plugins.th.tax_th`
- [ ] `ComplianceProvider <- plugins.th.compliance_th`
- [ ] `BankFormatProvider <- plugins.th.banks_th`

## Phase 5 — Endpoint Refactor (No API Break)

- [ ] `POST /payroll/run` calls `TaxProvider`
- [ ] `POST /payment/dispatch` calls `BankFormatProvider`
- [ ] `POST /tax/generate` calls `ComplianceProvider`
- [ ] Keep existing response schema as much as possible (backward compatible)

## Phase 6 — Data Model Cleanup

- [ ] Separate local-compliance fields from core payloads
- [ ] Add `country_code` into payroll run context
- [ ] Store compliance documents as generic records + subtype metadata

## Phase 7 — Test Matrix

- [ ] Unit tests:
- [ ] core engines contain no country-specific keywords
- [ ] TH plugin calculations match expected rules
- [ ] Integration tests:
- [ ] `COUNTRY=TH` flow passes all 5 phases
- [ ] Contract tests:
- [ ] every plugin passes the same contract signature

## Phase 8 — Rollout Plan

- [ ] Enable feature flag: `USE_COUNTRY_PLUGIN=true`
- [ ] Run shadow mode comparing old/new for 1-2 payroll cycles
- [ ] Compare:
- [ ] net pay per employee
- [ ] tax/sso totals
- [ ] generated document totals
- [ ] switch production traffic to 100% only after parity checks pass

## Current Project Mapping

Current files that are universal-like (should live in core):

- `hr_bot/events.py`
- `hr_bot/handlers/attendance_engine.py`
- `hr_bot/handlers/payroll_engine.py` (aggregator part)
- `hr_bot/handlers/leave_updater.py`
- `hr_bot/services/ai_service.py`
- `hr_bot/services/notify_service.py`
- `hr_bot/services/finance_service.py`

Current files that are TH-specific (should move to `plugins/th`):

- `hr_bot/services/tax_builders.py`
- `hr_bot/handlers/tax_document_generator.py`
- Thailand tax/SSO calculations in `hr_bot/finance_math.py`
- PND1/SSO deadline rules in flow
- Thailand bank formats in `hr_bot/services/bank_file_builder.py`
- PRISM integration (`hr_bot/services/prism_service.py`)

## Definition of Done

- [ ] add a new country (e.g., SG) by creating a new plugin only
- [ ] no core file changes required for new legal rules
- [ ] regression tests pass on all existing endpoints
- [ ] architecture and plugin-contract documentation are fully updated

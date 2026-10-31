---
name: smms-maintenance-workflows
description: Documents and checks the real SMMS work-order lifecycle (statuses, transitions, roles, info requests, approval, materials and procurement links, SLA pause and escalation, emergency, requester confirmation, audit, notifications) and maps business scenarios to Implemented / Partial / Not implemented with code evidence. Use when asked how a scenario works, whether a stage exists, or before changing WorkflowEngine, WorkOrderService or the workflow package.
---

# SMMS maintenance workflows

Verified against `claude/feature-program-1` (a21bfb8). Paths are relative to the repository root; `SMMS` means `Desktop/SMMS-FINAL`, `JAVA` means `SMMS/backend-source/src/main/java/com/smms`.

## When to use
Questions like "does the system support procurement, returns, reassignment, escalation?"; reviewing a change to status handling; designing workflow tests; reconciling the business description with the code.

## Inputs / scope
The scenario(s) to map. The CODE is the source of truth, then `SMMS/CLAUDE.md` for rules, then `SMMS/docs/implementation-ledger.md` and `SMMS/docs/work-log.md` for what each work stream delivered. Never invent a stage the code does not contain: record it as a GAP with the grep that shows its absence. Documents and older reports can be stale; re-check each claim.

## Relevant files
- `JAVA/enums/TicketStatus.java` (9 statuses), `ApprovalDecision`, `TicketPriority`, `UserRole`, `RequesterConfirmation`
- `JAVA/service/WorkflowEngine.java` (transition map and role sets; `system_admin` may do any structurally valid transition)
- `JAVA/service/WorkOrderService.java` (`create`, `createGenerated`, `transition`, `rejectDedicatedEndpointTransition`, `requestInfo`/`provideInfo`, `assign`, `warehouseAction`, `approvalDecision`, `close`, `reopen`, `lock`/`unlock`, `search`, `getHistory`)
- `JAVA/controller/WorkOrderController.java` and `JAVA/workflow/WorkOrderWorkflowController.java` (endpoints and `@PreAuthorize`)
- `JAVA/workflow/`: `EscalationService` (levels 1-3), `EmergencyService`, `RequesterConfirmationService`, `RatingService`, `StatusLinkService` and `PublicStatusController`, `SlaPause`, `WorkNoteService`, `WorkOrderHistoryWriter`
- `JAVA/service/NotificationService.java`, `JAVA/notify/` (deliveries, preferences), `JAVA/scheduler/SlaScheduler.java` (`app.escalation.check-ms`, default 5 minutes)
- `JAVA/materials/` (material requests: approve, reserve, issue, return, consume, close, cancel, purchase order), `JAVA/procurement/` (suppliers, purchase orders, receipts), `JAVA/inventory/` (stock ledger), `JAVA/pm/` (preventive-maintenance plans that generate work orders)
- Migrations V13, V20-V25 (workflow), V30-V39 (inventory, procurement, materials), V41-V44 (PM, downtime), V50-V51 (notifications); `V1__init.sql` (SLA and ticket-number triggers)
- `application.yml` and `application-prod.yml` (`app.sla.*`, `app.escalation.*`, `app.pm.*`)
- Tests under `SMMS/backend-source/src/test/java/com/smms/`: `service/WorkflowEngineTest`, `WorkOrderServiceTest`, `WorkOrderWorkflowM3Test`, `authz/WorkOrderTransitionMatrixTest`, `authz/WorkOrderVisibilityMatrixTest`, `materials/`, `procurement/StatusMachinesTest`, `pm/`, `enums/TicketStatusTest`
- `SMMS/docs/qa/test-plan.md` (scenario IDs and expected results; re-check against code, do not trust)

## Procedure
1. **Statuses.** new, under_review, assigned, in_progress, waiting_materials, waiting_approval, completed, closed, cancelled. Terminal: closed, cancelled. Return-for-information is a stage label (`info_requested`) on an under_review ticket, not a status. JSON uses lowercase DB values; `TicketStatus` also has a lenient parser for request bodies (DB value or enum name, any case).
2. **Transitions.** Copy the `TRANSITIONS` map from `WorkflowEngine` into your notes verbatim (from, to, roles). Then list what the generic `POST /{id}/transition` rejects and routes to dedicated endpoints (`rejectDedicatedEndpointTransition`): to `assigned` (use `/assign`), from `waiting_approval` for non-admins (use `/approval`), `completed` to `in_progress` (use `/reopen`). `system_admin` is exempt from the `waiting_approval` rule only.
3. **Dedicated endpoints.** `/assign` (only from under_review, not while info is requested; the technician must be active, a `technician`, in the ticket's own center and tenant), `/request-info` and `/provide-info` (stay under_review; the SLA clock pauses), `/warehouse`, `/approval` (approved or purchase_request go to in_progress; rejected goes to waiting_materials with a reason), `/close`, `/reopen` (increments `reopenedCount`, clears the requester verdict), `/lock` and `/unlock`, `/escalate`, `/emergency` and `/emergency/clear`, `/confirm`, `/rating`, `/status-link`, `/notes`.
4. **Roles per step.** Cross-check each `@PreAuthorize` with the engine's role sets and the access policy (`smms-tenant-isolation`); list mismatches, for example `system_admin` is not allowed on `/warehouse` or `/approval`, and endpoints with only `isAuthenticated()` rely on service-level checks.
5. **SLA, pause and escalation.** The SLA deadline is set by a DB trigger on insert (`V1__init.sql`: critical 4 h, high 8 h, medium 24 h, low 48 h); `app.sla.*` exists in the prod yml; check which source actually drives the deadline and which code recomputes it for pauses and emergencies (`SlaPause`, `EmergencyService`). `SlaScheduler` runs `EscalationService.runScheduledPass`: level 1 at breach, level 2 after `level2-factor` times the SLA, level 3 manual only; one row per (work order, level) via `ON CONFLICT DO NOTHING`; paused tickets are never breached or escalated.
6. **Audit and notifications.** Every state change goes through `recordHistory` (verify `create`, `transition`, `assign`, `warehouseAction`, `approvalDecision`, `close`, `reopen`, info request, escalation, emergency; `lock`/`unlock` do not). `NotificationService` notifies control room on create, assignee and requesters on transitions, approvers on `waiting_approval` (`notifyApprover`, falling back to maintenance managers with a warning), escalation recipients by level, and emergency recipients; dispatch to email/SMS is in `notify/` and depends on configured providers.
7. **Materials and procurement.** `/warehouse` only moves the ticket (materials available, or sent for approval); stock reservation, issue, return and consumption are in the material-request API (`/api/work-orders/{woId}/material-requests`, `/api/material-requests/{id}/...`) backed by `StockLedgerService` (`MANDATORY` transaction, append-only ledger). Purchase orders and receipts live under `/api/procurement`; a material request can create a purchase order. Check whether a new change keeps the ticket status and the material request status consistent, since they are separate state machines.
8. **Scenario mapping.** For each scenario fill: steps, actors, Status (Implemented / Partial / Not implemented), evidence `file:line`, gap. Re-verify each line before reporting; start from these hypotheses:
   - Routine repair, no parts: new, under_review, assigned, in_progress, completed, closed.
   - Parts from stock: ticket `/warehouse` plus material-request reserve, issue and consume; confirm how the two are linked.
   - Parts unavailable, procurement, receipt: `/warehouse` false, waiting_approval, approval, purchase order, receipt, stock update; check whether a receipt automatically moves the ticket.
   - Failed repair, reopen, escalation: reopen and escalation levels exist; check whether technician reassignment after `assigned` exists (`/assign` only allows under_review).
   - Return for information: request-info and provide-info with SLA pause.
   - Emergency: declare and clear, with an escalation level.
   - Requester confirmation and rating: accepted or disputed, 30-day rating window, public status link.
   - Preventive maintenance: plans generate work orders daily (`PmScheduler`).
   - Department and role `other` submissions: check `validateSubmitterRole` and department scoping.
9. **Never invent.** If a requested stage is absent, list it in the gaps with the grep that proves it, for example `grep -rni "resubmit\|reassign" JAVA`.

## Expected output
Scenario table: `Scenario | Steps (actor, status) | Status | Evidence | Gap`.
Findings table:

| ID | Severity | File:line | Evidence | Recommendation | Verified? |
|----|----------|-----------|----------|----------------|-----------|
| WF-001 | Medium | path:line | description | route through the dedicated endpoint | verified by test / code-reading only |

Gaps are listed as `GAP-xx` (feature absent), separate from defects (feature present but wrong).

## Verification
- `cd SMMS/backend-source && mvn -q test`; new transition rules need a table-driven test (from, to, role, expected) in `WorkOrderTransitionMatrixTest`.
- Live check, token from the environment (never printed): `curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"targetStatus":"under_review"}' http://localhost/api/work-orders/$ID/transition`.
- History: `GET /api/work-orders/$ID/history` must show one row per transition.

## Safety restrictions
Read-only by default; live probes only on tickets you created for the test. Never reset, reseed or drop the DB or delete Docker volumes (`docker compose down -v` forbidden). Never print or commit passwords, tokens or `.env` contents. Never make ports public. No destructive or DoS testing. Never merge to main. Fixes only when bounded, justified and covered by a regression test; stop and ask before schema migrations or architectural changes (new statuses, new state machines). Distinguish PASS/FAIL/BLOCKED/NOT TESTED; never claim a feature exists without code evidence.

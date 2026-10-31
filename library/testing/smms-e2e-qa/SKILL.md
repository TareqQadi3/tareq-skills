---
name: smms-e2e-qa
description: Executes the SMMS multi-role QA campaign (docs/qa/test-plan.md plus the Feature Program 1 modules) at API and browser level, recording PASS/FAIL/BLOCKED/NOT TESTED with request references and screenshots. Use when asked to run, continue or re-run the E2E/UAT campaign, verify a scenario, or produce QA evidence.
---

# SMMS end-to-end QA

Verified against `claude/feature-program-1` (a21bfb8). Paths are relative to the repository root; `SMMS` means `Desktop/SMMS-FINAL`.

## When to use
Running or extending the campaign in `SMMS/docs/qa/test-plan.md`, re-testing after a fix, or checking one role or endpoint. Planning and defect triage belong to the strongest available model; step execution and evidence recording to the implementation model.

## Inputs / scope
- Target: a running stack. Prefer an isolated throwaway stack (own compose project name, prod profile, nginx entry) over a shared environment; the default entry is `http://localhost`, API `http://localhost/api`.
- Accounts: usernames only, from section 2 of the test plan (`admin`, `Nasser`, `Tareq`, `cr.residential`, `cr.hospital`, `cr.it`, `cr.medical`, `tech.residential`, `tech.hospital`, `tech.it`, `tech.medical`, `maint.manager`, `elec.manager`, `warehouse`, `opco.manager`, `resident`, `department`, `other.user`). Passwords are NEVER written to any file; read at runtime from the environment or prompt the user.
- Scenario subset requested by the user (default: the regression gate first).

## Relevant files
- `SMMS/docs/qa/test-plan.md` (roles, permission matrix, workflow, QA and GAP IDs), `test-results.md` (results table), `evidence/README.md` (evidence rules). The plan was written for an earlier code state: its header says "plan only", its scenario labels (for example "reassignment partial", "inventory out of scope") predate Feature Program 1, and its "Updates after audit/fixes" section lists fixed defects and new tests. Treat every expected result as a hypothesis and re-derive it from the code with `smms-maintenance-workflows`.
- `SMMS/docs/implementation-ledger.md` and `SMMS/docs/work-log.md` (Entry 13: what was built and what was NOT tested), `SMMS/docs/db-integration-tests.md`
- `SMMS/scripts/seed-test-accounts.sh` (dry run by default; `--apply` creates only missing accounts; refuses writes outside a Codespace unless `SMMS_ALLOW_NON_CODESPACE=1`; `--reset-password` is risky, see safety)
- Endpoints under test: `WorkOrderController`, `workflow/WorkOrderWorkflowController`, `AuthController`, `UserController`, and the controllers in `assets`, `inventory`, `materials`, `procurement`, `pm`, `reports`, `notify`
- Frontend: `SMMS/frontend/src/app/` (pages, including `tech/*`), `src/lib/api.ts`; existing automated suites: Vitest (`npm test`), Playwright specs in `SMMS/frontend/e2e/` (mocked API, local only), backend `mvn test`
- `SMMS/nginx/nginx.conf` (public entry `/api/`, `/ws/`, `/uploads/` denied)
- Outputs (relative to `SMMS`): `docs/qa/test-results.md`, `docs/qa/evidence/`

## Procedure
1. **Pre-flight.** `curl -s -o /dev/null -w "%{http_code}\n" http://localhost/health` should be 200; if the app is down, mark everything BLOCKED and stop (do not start or stop services unless asked). Record the commit under test.
2. **Accounts.** Dry run first: `bash Desktop/SMMS-FINAL/scripts/seed-test-accounts.sh` (prompts for the admin password, hidden). Report which accounts are missing. Run with `--apply` ONLY after the user explicitly authorizes it for the target environment. Never use `--reset-password` without separate approval.
3. **Tokens.** Log in per role via `POST /api/auth/login` with a body built from environment variables; keep tokens in shell variables or a mode-600 file in the scratchpad; never echo them or include them in results (reference requests by method, path, status, ticket number, timestamp). Access tokens expire and refresh tokens must not work as access tokens.
4. **Regression gate.** The entry-gate items QA-050..053 describe defects that were later fixed (lowercase status and sub-type values, `ticketNumber` and `slaDeadline` in the create response). Run them as regression checks; if any fails, stop the campaign and report BLOCKED for the scenarios that depend on it.
5. **Per scenario step.** Perform each QA ID at API level (curl with `$TOKEN`), then confirm in the browser where the plan says UI. Record: QA ID, actor username, action, expected, actual, HTTP status, request reference (for example `POST /api/work-orders/{id}/assign -> 200`, ticket `WO-...`), result, evidence file. Ticket data is labelled (title prefix `QA-<id>`).
6. **Negative tests (mandatory per scenario).** Wrong-role token gives 403 (technician calling `/assign`, resident calling `/warehouse`); no token gives 401; refresh token as Bearer gives an authentication error; invalid transition is rejected; missing required fields give 400; another technician's or another center's ticket gives 403/404; a disallowed upload type is rejected; do not test size limits with large repeated uploads (one request at most, only if authorized).
7. **Feature Program 1 coverage.** Beyond scenarios A-H, plan checks for: info request and provide-info with SLA pause, escalation levels, emergency declare and clear, requester confirmation and rating, public status link, material request lifecycle against stock (reserve, issue, return, consume), purchase order approve and receive (separation of duties, over-receipt), asset register and PM plan generation (including the known medium defect that "generate now" creates one order per call), reports and CSV exports by role, notification preferences and deliveries, and the technician mobile app including offline replay. Mark NOT TESTED what needs a real device or provider (Safari/iPhone, HEIC, real SMTP/SMS, several backend replicas).
8. **GAP items.** `GAP-xx` rows record "Not implemented (code evidence: file)", never a FAIL of a delivered feature; re-confirm absence by grep before writing, since several old GAPs were closed.
9. **Browser steps.** Use preinstalled Chromium only: `export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`; never `playwright install`. Real screenshots only, named `QA-###-<step>.png`, saved in `SMMS/docs/qa/evidence/`. Do not capture login forms with typed passwords. Mocked Playwright specs are not evidence of the running stack.
10. **Results file.** Append to `docs/qa/test-results.md` one table per run: `Run date | Commit | Env | QA ID | Actor | Result | Request ref | Evidence | Notes`. Vocabulary: PASS, FAIL, BLOCKED (state the missing precondition), NOT TESTED. Never mark PASS from code reading alone.
11. **Defects.** For each FAIL add a finding with a minimal reproduction and severity; propose a fix only if bounded and covered by a regression test, otherwise hand it to the planning model.
12. **Cleanup.** Only records created by this run (the `QA-<id>` label and recorded ids), and only if the user authorized cleanup; prefer leaving closed or cancelled test tickets. Never bulk-delete, never touch seeded or user-created data (`Nasser`, `Tareq`, `admin`). A throwaway stack is removed only by its own project name and only when the user asked.

## Expected output
Run summary (counts of PASS/FAIL/BLOCKED/NOT TESTED), the results table appended to `docs/qa/test-results.md`, and findings:

| ID | Severity | File:line | Evidence | Recommendation | Verified? |
|----|----------|-----------|----------|----------------|-----------|
| QA-F-001 | High | path:line | step, status code, evidence file | fix idea | verified by run (request ref) |

## Verification
- Backend unit suite before and after any fix: `cd Desktop/SMMS-FINAL/backend-source && mvn -q test`; frontend: `npx tsc --noEmit && npm run lint && npm test`.
- Re-run the failing QA ID and its negative test; use the same evidence name with a `-retest` suffix.
- Cross-check the API result with `GET /api/work-orders/$ID/history` (one row per transition) and the UI.
- Confirm no credentials in outputs: `grep -rniE "password|bearer " Desktop/SMMS-FINAL/docs/qa | grep -v "never"` shows no values.

## Safety restrictions
Read-only by default; writes limited to labelled QA tickets and (with authorization) test accounts. Never reset, reseed or drop the DB or delete Docker volumes (`docker compose down -v`, `make clean` forbidden). Never print or commit passwords, tokens or `.env` contents; usernames only. Never make ports public. No destructive or DoS testing (no load, no repeated login failures to trigger lockout). Never merge to main. Fixes only when bounded, justified and covered by a regression test; stop and ask before schema migrations or architectural changes. Distinguish PASS/FAIL/BLOCKED/NOT TESTED; never claim a feature exists without code evidence; browser emulation is not a physical device.

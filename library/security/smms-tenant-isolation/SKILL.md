---
name: smms-tenant-isolation
description: Audits SMMS application-level multi-tenant and role-scope isolation (tenant_id, TenantContext, TenantSecurityService, WorkOrderAccessPolicy, region/center/control-room scoping). Use when reviewing any query, endpoint, scheduler or filter change that touches tenant data, or when asked whether one organization can see another's data.
---

# SMMS tenant and scope isolation

Verified against `claude/feature-program-1` (a21bfb8). Paths are relative to the repository root; `SMMS` means `Desktop/SMMS-FINAL`, `JAVA` means `SMMS/backend-source/src/main/java/com/smms`.

## When to use
A new repository query, controller, scheduler, notification or service; a suspected cross-tenant or cross-scope leak; a periodic isolation audit. Combine with `smms-security-review` for JWT aspects.

## Inputs / scope
Target branch/diff, base URL (default `http://localhost/api`), tokens per role read from the environment at runtime. Layers to check: (1) tenant (`tenant_id`); (2) role scope inside a tenant, defined for work orders by `WorkOrderAccessPolicy` (technician: assigned; resident/department: own submissions; control_room: own plus center AND assigned control rooms; hospital supervisor and managers: own plus center; warehouse: center tickets needing materials; region_supervisor: centers of the region; `other`: nothing); (3) module policies: `AssetAccessPolicy`, `InventoryAccess`, `procurement/CenterScope`, `AdminScopePolicy` (user administration).

## Relevant files
- `JAVA/util/TenantContext.java` (ThreadLocals; `clear()` removes them) and `JAVA/security/JwtAuthFilter.java` (tenant from the JWT `tenantId` claim only; subscription lifecycle: expired gives 402, suspended allows GET only; `TenantContext.clear()` in `finally`; a token with no tenant claim sets a NULL context, which means unrestricted/platform admin)
- `JAVA/security/TenantSecurityService.java` (`assertSameTenant`, `requireUser/Region/Center/ControlRoom`, `resolveAssignedToFilter`)
- `JAVA/security/WorkOrderAccessPolicy.java`, `WorkOrderScope.java` (single source of work-order visibility; out-of-scope reads return 404)
- `JAVA/security/AdminScopePolicy.java`, `JAVA/assets/AssetAccessPolicy.java`, `JAVA/inventory/service/InventoryAccess.java`, `JAVA/procurement/CenterScope.java`
- `JAVA/procurement/entity/TenantOwnedEntity.java` (tenant NOT NULL, not updatable) versus `JAVA/entity/BaseEntity.java` (nullable `tenant_id`)
- `JAVA/repository/`, `JAVA/service/`, and the feature packages `assets`, `inventory`, `materials`, `procurement`, `pm`, `workflow`, `notify`, `reports`, `department`, `diagnostics`
- `JAVA/scheduler/SlaScheduler.java`, `JAVA/pm/PmGenerationService.java`, `JAVA/workflow/EscalationService.java`, `JAVA/notify/DeliveryScheduler.java` (run without a request, so no TenantContext; they must filter by each row's tenant)
- `JAVA/controller/TenantAssignmentController.java` (`/tenantless-users`, admin assigns tenants), `JAVA/config/TenantIntegrityReporter.java`, `JAVA/diagnostics/` (platform diagnostics, ids and counts only)
- Migrations V4-V9, V60 (tenant backfill, NOT NULL and FK constraints added NOT VALID then validated, diagnostics views)
- Tests: `SMMS/backend-source/src/test/java/com/smms/authz/` (`TenantSecurityServiceTest`, `WorkOrderVisibilityMatrixTest`, `EndpointAuthorizationCoverageTest`), `util/TenantContextTest`, `diagnostics/`, and the opt-in `it/*DbIT` tests

## Procedure
1. **State the model.** Isolation is enforced in application code. There is no PostgreSQL row-level security (confirm: `grep -rin "row level\|create policy" SMMS/scripts SMMS/backend-source/src/main/resources/db/migration` returns nothing). RLS needs a migration, so it requires explicit approval; never add it unasked.
2. **Enumerate data access.** List every repository call in services, controllers, schedulers, listeners and event handlers of the packages above. For each: does the query carry the tenant (derived `...AndTenantId`, a `@Query` with `tenant_id`, or a Specification built from `WorkOrderAccessPolicy`), or does the code first call `tenantSecurity.require*` / `assertSameTenant`? Flag bare `findById`, `findAll`, `findByIdIn`, `existsById`, and every native query (`nativeQuery = true`, `JdbcTemplate` in `notify/JdbcDeliveryStore` and report code) without a tenant predicate.
3. **Platform branch.** When `TenantContext.get()` is null, the `require*` helpers fall back to unscoped lookups. Confirm only `system_admin` can reach it: tokens without a `tenantId` claim (refresh tokens, see `smms-security-review`) and non-admin users whose `tenant_id` is NULL (check `/api/admin/tenantless-users` and `TenantIntegrityReporter`). A new endpoint under a platform-admin role must say so in its authorization rule.
4. **ThreadLocal hygiene.** `JwtAuthFilter` clears in `finally`; early returns (402/403 `writeError`) are inside the try; no `@Async`, `@Scheduled`, `@TransactionalEventListener` or WebSocket path reads `TenantContext` (`grep -rn "TenantContext" JAVA/{scheduler,websocket,pm,notify,workflow,inventory}`). Background jobs must carry the tenant from the row they process.
5. **Write paths.** Create and update paths set the tenant from the context or from a verified parent, never from the request body. No request DTO has a `tenantId` field, and every referenced id (center, region, control room, department, asset, warehouse, item, supplier, assignee) is resolved through a tenant-checked lookup. New tables follow `TenantOwnedEntity` (NOT NULL, not updatable) and have a tenant index.
6. **Scope inside a tenant.** For any new list or detail path, check it goes through the module policy (`WorkOrderAccessPolicy`, `AssetAccessPolicy`, `InventoryAccess`, `CenterScope`) and not just the tenant. Compare with `SMMS/docs/qa/test-plan.md` and `SMMS/CLAUDE.md` section 4 (a simplified four-role matrix; the 13 real roles are defined by the policies above). Out-of-scope objects must give 404 where the policy says so, so ids are not an oracle. Missing scope data (no center, region or control-room rows) must grant nothing.
7. **Unauthenticated surface.** `/api/auth/**`, `/actuator/health`, `/ws/**` and `GET /api/public/**` (status links, rate limited) are permitted without a login. Check that public endpoints expose a single object via an unguessable token and no tenant data, and that the WebSocket handshake (`WsHandshakeInterceptor`, single-use ticket, fails closed) still authenticates and that messages are scoped to the user's tenant and role.
8. **Probe matrix (API).** Build a table role x endpoint x foreign id. Cross-tenant proof needs a second tenant, which is a write: propose it as clearly labelled TEST data (`ZZ-ISOLATION-TEST-*`), wait for approval, delete only what you created if authorized. Without it run intra-tenant probes (technician A vs B, resident vs another center, region supervisor vs other region) and mark cross-tenant rows NOT TESTED.

## Expected output
| ID | Severity | File:line | Evidence | Recommendation | Verified? |
|----|----------|-----------|----------|----------------|-----------|
| TEN-001 | e.g. High | path:line | query lacks tenant predicate / probe returned 200 | add tenant predicate or `require*` | by test / code-reading only |

Plus the probe matrix: rows = caller role, columns = resource owner, cells = PASS / FAIL / BLOCKED / NOT TESTED with HTTP code and request reference.

## Verification
- `cd SMMS/backend-source && mvn -q test`. A fix needs a test that sets `TenantContext.set(tenantA)` and asserts access to a tenant B entity throws `AccessDeniedException` or `ResourceNotFoundException`; extend `WorkOrderVisibilityMatrixTest` for new scope rules.
- Probe without printing tokens: `curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN_A" "http://localhost/api/work-orders/$ID_OF_B"`; expect 404/403, never 200.
- Never infer isolation from the UI hiding things; the server response is the evidence.

## Safety restrictions
Read-only by default. Never reset, reseed or drop the DB or delete Docker volumes (`docker compose down -v` forbidden). Never print or commit passwords, tokens or `.env` contents. Never make ports public. No destructive or DoS testing. Never merge to main. Test data only with user approval, labelled, and removed only if you created it and removal is authorized. Fixes only when bounded, justified and covered by a regression test; stop and ask before schema migrations (including RLS) or architectural changes. Distinguish PASS/FAIL/BLOCKED/NOT TESTED; never claim a feature exists without code evidence.

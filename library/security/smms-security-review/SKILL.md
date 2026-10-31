---
name: smms-security-review
description: Read-only OWASP Top 10 / API Top 10 security review of the SMMS Spring Boot + Next.js codebase (authN, sessions, authZ/IDOR, CORS, XSS, uploads, WebSocket, secrets, logging, error leakage, dependencies). Use when asked to audit security, review a PR for security impact, or check a suspected vulnerability.
---

# SMMS security review

Verified against `claude/feature-program-1` (a21bfb8). Paths are relative to the repository root; `SMMS` means `Desktop/SMMS-FINAL`, `JAVA` means `SMMS/backend-source/src/main/java/com/smms`.

## When to use
Security audit of the whole app or of a diff; triage of a suspected vulnerability; before exposing the app beyond localhost. For tenant-boundary depth use `smms-tenant-isolation`; for DB hardening use `smms-database-safety`.

## Inputs / scope
Branch or diff under review, target base URL (default `http://localhost/api`), and which roles have tokens available (tokens come from the environment at runtime, never typed into files). Default scope: backend, frontend API client, nginx, compose, env templates, CI workflows.

## Relevant files
- `SMMS/CLAUDE.md` (server-side enforcement rule), `SMMS/docs/security/` (`deployment-runbook.md`, `migrations-and-secrets.md`, `phase2-proposals.md`)
- `JAVA/config/SecurityConfig.java` (filter chain: `/api/auth/**`, `/actuator/health`, `/ws/**`, `GET /api/public/**` permitted; `/uploads/**` denied; everything else authenticated; CSRF off; stateless; CORS)
- `JAVA/security/JwtService.java` (`typ` claim access/refresh, session id `sid`), `JwtAuthFilter.java`, `BruteForceProtectionService.java`, `XssSanitizationFilter.java`
- `JAVA/auth/` (`AuthSessionService`, `WsTicketService`, `WsTicketController`, `AuthCleanupJob`), `JAVA/websocket/` (`WebSocketConfig`, `WsHandshakeInterceptor`)
- `JAVA/service/AuthService.java`, `UserService.java`, `AttachmentService.java`; `JAVA/controller/` and the controllers in the feature packages (`assets`, `inventory`, `procurement`, `materials`, `pm`, `workflow`, `notify`, `reports`, `diagnostics`)
- `JAVA/workflow/PublicStatusController.java`, `PublicStatusRateLimiter.java` (unauthenticated status links)
- `JAVA/exception/GlobalExceptionHandler.java`, `application*.yml`, `SMMS/backend-source/pom.xml`, `SMMS/frontend/package.json`
- `SMMS/frontend/src/lib/api.ts` (token storage and refresh), `SMMS/nginx/nginx.conf`, `SMMS/docker-compose*.yml`, `SMMS/.env.example`, `SMMS/.env.codespaces` (test-only values)
- `.github/workflows/secret-scan.yml` and `.gitleaks.toml` (history secret scan), `backend-tests.yml`, `frontend-ci.yml`
- Tests to extend: `src/test/java/com/smms/{security,auth,authz,exception,websocket}/` (`JwtServiceTest`, `JwtAuthFilterTest`, `SecurityChainTest`, `AuthSessionFlowTest`, `WsHandshakeInterceptorTest`, `EndpointAuthorizationCoverageTest`, `AttachmentEndpointsTest`)

## Procedure
1. **AuthN and sessions.** Access and refresh tokens carry a `typ` claim; `JwtService` refuses a refresh token (and legacy tokens without a role claim) as an access token; tokens are bound to a login session (`sid`) checked on each request. Verify that any change keeps: refresh tokens rejected as Bearer, rotation and revocation, expiry from `app.jwt.*`, no secret fallback. Prove with a test, not by assumption.
2. **Brute force.** `AuthService.login` calls `BruteForceProtectionService` (`isBlocked`, `recordFailure`, `recordSuccess`). nginx has no `limit_req`; check whether in-app throttling covers every credential endpoint (login, password change, public status links, WS ticket) and what happens when the throttle store is unavailable.
3. **Password handling.** BCrypt cost in `SecurityConfig`; password rules in `UserService` and the password request DTOs; reset passwords travel in a JSON body (`ResetPasswordRequest`), never as a query parameter (`grep -rn "@RequestParam.*[Pp]assword" JAVA`); forced password change (`mustChangePassword`) is enforced by `JwtAuthFilter`; default admin credentials are reported at startup (`DefaultCredentialsReporter`) and must not be printed.
4. **AuthZ coverage.** List every mapping (`grep -rn "Mapping(\|PreAuthorize" JAVA`). `EndpointAuthorizationCoverageTest` is the guard; a new endpoint without a class or method rule must be covered by an explicit service-level check, and the test updated. Methods that rely only on `anyRequest().authenticated()` need a role or ownership check inside the service.
5. **IDOR.** For every `{id}` path, confirm the lookup goes through the tenant and scope checks (`TenantSecurityService`, `WorkOrderAccessPolicy`, `AssetAccessPolicy`, `InventoryAccess`). Out-of-scope objects give 404. See `smms-tenant-isolation`.
6. **CORS and CSRF.** `CORS_ALLOWED_ORIGIN_PATTERNS` is wildcard-capable with credentials: the production value must be an explicit list. CSRF is off, acceptable only while auth is a Bearer header. Tokens live in `localStorage` (`api.ts`), so XSS is the main exposure; flag any move to cookies. `setAllowedHeaders("*")` is noted, not a finding by itself.
7. **XSS and input.** `XssSanitizationFilter` and `util/InputSanitizer` are regex based and bypassable; the real control is React output encoding: `grep -rn "dangerouslySetInnerHTML" SMMS/frontend/src`. Check `@Valid` and size limits on new DTOs.
8. **Uploads.** `AttachmentService`: extension allow-list (jpg, jpeg, png, pdf, doc, docx), server-side content type by extension (client type never stored), magic-byte check, at most 10 files per request, idempotency key format, stored name sanitized, downloads resolved against the upload root (`Files.size(real)` path). `/uploads/**` is denied; attachments are served only through the authorized endpoint. For a new upload path check size cap (nginx `client_max_body_size 50M`, Spring multipart), traversal, and that DTOs do not expose `filePath`.
9. **WebSocket.** The handshake is authenticated with a single-use ticket (`WsTicketController`, `WsHandshakeInterceptor`) and fails closed. Check ticket expiry and single use, origin checks, and that broadcast destinations are scoped by tenant and role.
10. **Public surface.** `GET /api/public/**` status links: unguessable token, rate limit (`PublicStatusRateLimiter`), response limited to one ticket's public fields, expiry.
11. **Secrets.** Run the grep block below. `application-prod.yml` must use `${VARS}`; dev literals are Low/Info if dev is never active in compose (`SPRING_PROFILES_ACTIVE: prod`). Only `.env.example` and `.env.codespaces` may be tracked among env files. Also check tracked agent settings: `git ls-files | grep -E "\.claude/settings(\.local)?\.json"` and read any hit for credentials in permission rules; report file and kind only. CI runs gitleaks on history.
12. **Sensitive logging and errors.** `grep -rnEi "log\.(info|warn|debug|error).*(password|token|secret)" JAVA`. `GlobalExceptionHandler` must give the catch-all a generic message; prod sets `server.error.include-message: never` and `include-stacktrace: never`.
13. **Dependencies.** Record versions from `pom.xml` and `package.json`; `npm audit --omit=dev` and `mvn dependency:tree` only if the network permits, otherwise NOT TESTED.

```bash
cd Desktop/SMMS-FINAL
grep -rnEi "(password|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_-]{8,}" backend-source/src frontend/src scripts *.yml *.sh 2>/dev/null | grep -v "\${" | cut -c1-160   # review hits, never paste values into reports
git ls-files | grep -E "(^|/)\.env"
grep -rnEi "log\.(info|warn|debug|error).*(password|token|secret)" backend-source/src/main
grep -rn "@RequestParam.*[Pp]assword" backend-source/src/main
```
When reporting a secret hit, cite file:line and the kind only, never the value.

## Expected output
Findings in the chat (or a file under `Desktop/SMMS-FINAL/docs/qa/` if asked):

| ID | Severity | File:line | Evidence | Recommendation | Verified? |
|----|----------|-----------|----------|----------------|-----------|
| SEC-001 | High | path:line | quoted code / probe result | bounded fix | verified by test / code-reading only |

Severities: Critical / High / Medium / Low / Info. Add a PASS/FAIL/BLOCKED/NOT TESTED line per OWASP area.

## Verification
- `cd Desktop/SMMS-FINAL/backend-source && mvn -q test`.
- API probes (token from the environment, never echoed): `curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN_ROLE" http://localhost/api/admin/users`. Expect 401 without a token, 403 for a wrong role, 404 (not 200) for another tenant's id.
- Refresh-token check: send a refresh token as the Bearer to a protected endpoint; expect 401 (`SecurityChainTest.refreshTokenAsBearerIs401`).
- A fix is accepted only with a regression test that fails before and passes after.

## Safety restrictions
Read-only by default. Never reset, reseed or drop the DB or delete Docker volumes (`docker compose down -v`, `make clean` are forbidden). Never print or commit passwords, tokens or `.env` contents. Never make ports public. No destructive or DoS testing (no flooding logins to prove brute force; reason from code). Never merge to main. Fixes only when bounded, justified and covered by a regression test; stop and ask before schema migrations or architectural changes. Report PASS / FAIL / BLOCKED / NOT TESTED honestly, and never claim a feature exists without code evidence.

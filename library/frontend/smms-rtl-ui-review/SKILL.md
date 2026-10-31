---
name: smms-rtl-ui-review
description: Reviews the SMMS Arabic-first RTL Next.js 14 + Tailwind + shadcn UI for direction, logical CSS, formatting, accessibility, contrast, tap targets, responsiveness (390x844 and 1440x900), offline/mobile technician screens and state handling, using Playwright screenshots of real pages. Use when asked to audit or QA the UI, RTL or mobile layout, or after front-end changes.
---

# SMMS RTL / UI review

Verified against `claude/feature-program-1` (a21bfb8). Paths are relative to the repository root; `SMMS` means `Desktop/SMMS-FINAL`, `FE` means `SMMS/frontend/src`.

## When to use
UI audit, RTL regression check, mobile layout check, accessibility pass, or visual evidence for a QA run. Not for backend behavior (use `smms-e2e-qa`).

## Inputs / scope
Base URL of a running app (default `http://localhost`), accounts by username only (passwords read from the environment at runtime, never written down), and the pages to cover. Routes under `FE/app`: `login`, `dashboard`, `work-orders`, `new-request`, `my-requests`, `my-tasks`, `approvals`, `tech` (mobile technician app, with `history` and `notifications`), `status/[token]` (public status page), `assets`, `maintenance-plans`, `inventory`, `procurement`, `material-requests`, `departments`, `reports`, `users`, `regions`, `centers`, `control-rooms`, `admin`, `settings`, `config`. Language values are `ar` (default) and `en` (`smms_lang` in localStorage, set in `FE/store/authStore.ts`).

## Relevant files
- `FE/app/layout.tsx` (`<html lang="ar" dir="rtl">`, Cairo font with arabic and latin subsets), `FE/app/globals.css`
- `FE/components/layout/DashboardLayout.tsx`, `Sidebar.tsx`, `Topbar.tsx`; `FE/app/tech/layout.tsx` and `FE/components/tech/TechShell.tsx` (mobile shell)
- `FE/lib/i18n.ts` (ar/en dictionaries, `useT`), `FE/lib/module-i18n.ts` (`useModuleT`, returns `dir`), `FE/components/common/i18n.ts` (shared strings), `FE/hooks/useTranslate.ts`
- `FE/components/common/` (`ConfirmDialog`, `EmptyState`, `ErrorState`, `LoadingState`, `PermissionDenied`, `Pagination`, `FormField`), `FE/components/ui/` (shadcn)
- `FE/modules/*` (feature modules: assets, departments, inventory, materials, pm, procurement, reports, requests, tech, workflow), `FE/modules/tech/format.ts` (`relativeTime` with Latin digits), `FE/lib/utils.ts` (`Intl.DateTimeFormat` helpers)
- `FE/lib/offline/` and `FE/lib/ws.ts` (offline queue and WebSocket; user-visible state for pending/failed actions)
- `SMMS/frontend/tailwind.config.ts` (no RTL plugin; `tailwindcss-animate`; `font-sans` = Cairo), `components.json`, `package.json` (Next 14.2.35, Tailwind 3.4, Vitest, Playwright)
- Existing tests: `*.test.tsx` beside components (Vitest) and `SMMS/frontend/e2e/*.spec.ts` (Playwright, mocked API)
- Role and menu map: `SMMS/docs/qa/test-plan.md`

## Procedure
1. **Static pass (greps).**
```bash
cd Desktop/SMMS-FINAL/frontend/src
grep -rnE "\b(ml|mr|pl|pr)-[0-9]|text-(left|right)\b|\b(left|right)-[0-9]|rounded-[lr]-|border-[lr]\b" app components modules   # physical properties; prefer ms/me/ps/pe/start/end, rounded-s/e, border-s/e
grep -rn "dir=" app components modules                  # where direction is overridden (portals, mixed-language blocks)
grep -rnE "ChevronLeft|ChevronRight|ArrowLeft|ArrowRight" app components modules   # directional icons need rtl:rotate-180 or swapping
grep -rnE "toLocale|Intl\.|new Date|date-fns|\.toFixed" app lib modules components   # number/date formatting must follow the language
grep -rnE "h-[4-9] |h-8|w-8|size=\"sm\"|text-\[1[0-2]px\]|text-xs" app components modules | head -40   # small targets / tiny text
```
   The tree mixes physical (`ml-`, `pr-`) and logical (`ms-`, `pe-`) classes; treat counts per file as candidates and confirm visually.
2. **Direction.** The root sets `dir="rtl"`. Confirm every route flips correctly when the language is `en` (components using `useModuleT` read `dir`), and that dialogs, sheets and portals render with the right direction.
3. **Run the screenshots (real pages only).** Playwright and Chromium are preinstalled; never run `playwright install`, never fabricate or edit a screenshot.
```bash
export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
mkdir -p Desktop/SMMS-FINAL/docs/qa/evidence
node ui-shots.js   # your script kept in the session scratchpad, not in the repo
```
   Script outline: launch chromium headless; contexts `{viewport:{width:390,height:844}, deviceScaleFactor:3, isMobile:true, hasTouch:true}` and `{viewport:{width:1440,height:900}}`; log in through the real form using `process.env.UI_USER` / `process.env.UI_PASS` (never log them); for each page `page.goto`, wait for network idle, `page.screenshot({path, fullPage:true})`; save to `Desktop/SMMS-FINAL/docs/qa/evidence/UI-<page>-<ar|en>-<390|1440>.png`. Capture console errors and horizontal overflow (`document.documentElement.scrollWidth > innerWidth`). The repository's own e2e specs use mocked API responses; they prove component behavior, not the running stack.
4. **Checklist per page and viewport:** RTL mirroring of layout, sidebar side and drawer direction; mirrored directional icons; logical CSS; numbers and dates (one digit style, Latin or Arabic-Indic, consistently across table, badge and chart; the code uses Latin digits in relative times); mixed Arabic/English strings (ticket numbers `WO-...`, SKUs, emails, usernames) wrapped in `dir="ltr"` or `<bdi>`; form labels, required markers and inline errors in the active language; visible focus rings (Tab through the page); keyboard operability of dialogs, selects and tabs (Esc closes, focus returns); WCAG AA contrast 4.5:1 (check light grays on white, badges, disabled states, computed from `getComputedStyle`); tap targets of at least 44x44 px at 390 wide; tables scroll inside a wrapper without breaking the page; empty, loading, error and permission-denied states exist and are translated (`components/common`); Arabic line-height with Cairo; consistency of shadcn components (button sizes, input heights, radius).
5. **Mobile technician app.** On `tech/*` at 390 wide: bottom/shell navigation reachable with one hand, action buttons not hidden by the keyboard, photo upload and notes panels usable, offline and pending-action indicators visible and translated, conflict banner readable, and the public `status/[token]` page shows no internal data.
6. **Device honesty.** A 390x844 Chromium context is an emulation, not a physical iPhone: Safari-specific issues (100vh, safe-area, input zoom below 16 px font, date pickers, camera capture) are NOT TESTED unless a real device was used. Say so in the report.
7. **Role views.** Repeat key pages for roles whose menu differs (technician `tech`/`my-tasks`, resident `new-request`/`my-requests`, `control_room`, warehouse, `system_admin`); screens a role cannot reach are recorded, not skipped.

## Expected output
Findings table plus a screenshot index (path, page, viewport, language, role):

| ID | Severity | File:line | Evidence | Recommendation | Verified? |
|----|----------|-----------|----------|----------------|-----------|
| UI-001 | Medium | frontend/src/app/x/page.tsx:NN | `ml-2` on icon, screenshot `docs/qa/evidence/UI-...png` | use `me-2` | verified by screenshot / code-reading only |

Severity guide: Critical = unusable or data-hiding in RTL; High = key flow broken on mobile; Medium = wrong mirroring or contrast; Low = polish; Info = observation.

## Verification
- Re-run the same script after a fix and compare the new screenshot with the old (keep both).
- `cd Desktop/SMMS-FINAL/frontend && npx tsc --noEmit && npm run lint && npm test` (the CI frontend job runs the same three steps; `next build` also enforces types and lint).
- Contrast: report the computed ratio and both colors.

## Safety restrictions
Read-only against the app: no form submissions that create data unless the user approved a labelled test record. Never reset, reseed or drop the DB or delete Docker volumes (`docker compose down -v` forbidden). Never print or commit passwords, tokens or `.env` contents; never write credentials into scripts or screenshots (crop or avoid pages that display tokens). Never make ports public. No destructive or DoS testing. Never merge to main. Fixes only when bounded, justified and covered by a test or before/after screenshot; stop and ask before architectural changes (for example a global i18n router). Distinguish PASS/FAIL/BLOCKED/NOT TESTED; never claim a feature exists without code evidence. Do not run `playwright install` or download browsers.

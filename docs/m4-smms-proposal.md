# M4 — SMMS skill set (approved 2026-10-31; imported, not applied)

Record for the M4 approval gate ("owner approval per skill", `implementation-plan.md`).
The owner approved O-16…O-19 (decisions D-28…D-31). The 8 skills are now in the library
(`catalog/skills.yaml`, `library/`); nothing has been applied to SMMS. Sections 1-6 are the
analysis as inspected on 2026-10-30 from `TareqQadi3/smms-final` (read-only clone) and the pinned
upstream repositories; section 7 records the outcome.

## 1. SMMS as inspected

| Item | Finding |
|---|---|
| Repository | Public. `main` is stale (2026-06-12, 394 files, **no skills**). The active line is `claude/feature-program-1` (2026-10-29, `a21bfb8`, 1,764 files). Eight other `claude/*` branches carry the same 111 skills. |
| Stack | Java 21 / Spring Boot 3.3.0; PostgreSQL 16 with **Flyway** (38 migrations, V1–V60); Redis; JWT; WebSocket; Next.js 14.2 / React 18 / TypeScript / Tailwind 3 / shadcn; Docker Compose + nginx; Arabic-first RTL. Manager `scan` result: docker, flyway, java, nextjs, nodejs, postgres, react, rtl-arabic, spring-boot, typescript. |
| Domain | Multi-tenant (`tenant_id`, `TenantContext`, no row-level security), 13 roles, work-order workflow engine, file uploads (11 `MultipartFile` uses), one native query, no outbound HTTP, no process execution. |
| Quality gates | 127 backend test files (1,219 tests per its work log), Vitest + Playwright, three CI workflows (backend, frontend, secret-scan). |
| Working rules | `CLAUDE.md` §6: Opus plans, Sonnet implements, never merge to `main` without approval. |
| Hygiene | `backend-source` and `enterprise-workspace/backend-source` (and the two frontends) are diverged copies. |

## 2. Findings that change the plan

1. **The 111 skills exist only on feature branches.** A checkout of `main` has none, so any
   "state of SMMS" must name the branch. Baseline used here: `claude/feature-program-1`.
2. **The six SMMS project skills are stale.** Every file path they cite still exists, but none
   mentions Flyway (`smms-database-safety` still teaches `init.sql` + `scripts/V2`). Also wrong
   now: `smms-maintenance-workflows` says inventory has no service layer (there is an
   `inventory/` package with repositories and services), that `notifyApprover` is empty (it is
   implemented), and that reassignment, escalation, and procurement are absent (code exists).
   They must be refreshed before activation.
3. **Provenance and licenses.** All 86 skills with a `SOURCE.txt` are byte-identical to
   `TareqQadi3/spruvex-r@86b8eac` (verified). That repository ships **no license files** for
   them; only 3 declare a usable license (`openweb` MIT, `playwright-skill` MIT, `postgres`
   Apache-2.0), 5 say "Complete terms in LICENSE.txt" with no such file, and 25 skills have
   no `SOURCE.txt` at all (the six project skills, 18 pentest skills, `anydesign`). Under D-15
   none of these can be active without verified license information.
4. **Upstream found for the two general skills** (below): exact commit, MIT.
5. **Manager defect fixed:** `scan` descended into `.claude/skills/*` and reported Python and
   Node from a skill's own manifests. Skill directories are now pruned (test + mutation check).
6. **Manager improvement:** `add-skill --authored` can record where an authored skill was
   derived from (needed for the SMMS-authored skills).
7. **Security finding in SMMS (reported, not touched):** the committed
   `Desktop/SMMS-FINAL/.claude/settings.local.json` contains a plaintext login credential in a
   permission rule, on `main` and on the active branch of a public repository.

## 3. Proposed set: 8 skills, 2,014 description characters

| Skill | Scope | Source and pin | License | Chars | Why SMMS needs it |
|---|---|---|---|---|---|
| `smms-tenant-isolation` | project | SMMS `a21bfb8`, owner-authored | internal (D-23) | 314 | Tenant isolation is enforced only in application code; 13 roles |
| `smms-security-review` | project | same | internal | 285 | JWT, uploads, CORS, WebSocket; replaces the 18 generic pentest skills |
| `smms-database-safety` | project | same | internal | 243 | PostgreSQL 16, Flyway, native enums, backups |
| `smms-maintenance-workflows` | project | same | internal | 376 | Work-order lifecycle and SLA |
| `smms-rtl-ui-review` | project | same | internal | 335 | Arabic RTL Next.js UI |
| `smms-e2e-qa` | project | same | internal | 291 | Multi-role QA campaign (`docs/qa/test-plan.md`) |
| `systematic-debugging` | general | `obra/superpowers@c8921b5` v6.1.1 (2026-07-23) | MIT | 91 | Root-cause discipline; 1,219 backend tests |
| `test-driven-development` | general | `obra/superpowers@b9e75dd` v6.1.1 (2026-07-05) | MIT | 79 | Same, test-first |

Packs: `core` (default; the two general skills) and `smms-core` (the six project skills,
named explicitly by SMMS's config, never auto-proposed). Review of the two general skills:
frontmatter has only `name` and `description` (no capability grants); the one script,
`find-polluter.sh`, is a local test-bisection helper with no network use. Both upstream
trees are byte-identical to the SMMS copies. Project skills: no capability grants; the
"destructive" matches are prohibitions ("FORBIDDEN: DROP, TRUNCATE…").

## 4. Not proposed (103 skills)

| Group | Count | Reason |
|---|---|---|
| Marketing, growth, sales, content | 50 | Off-domain |
| Offensive / pentest security (no `SOURCE.txt`) | 18 | Origin unrecorded; duplicate the project security and tenant skills; dual-use |
| Design and creative (`better-*`, `anydesign`, `taste-skill`, …) | 10 | Overlap `smms-rtl-ui-review`; not needed |
| SaaS and messaging integrations | 13 | Not used by SMMS |
| Other tooling | 12 | `postgres` (executable query runner; `smms-database-safety` already covers safe queries), `playwright-skill` / `webapp-testing` (SMMS has its own Playwright suite), `erp-pos-saas-architect` (NestJS stack), `subagent-driven-development` (matches no upstream commit), `finishing-a-development-branch` / `using-git-worktrees` (not needed) |

Account-level skills (`smms-deployment-expert`, `smms-system-engineer`, `smms-backend-builder`,
`token-optimizer`, `build-engineer`, `professional-full-stack-debug-build-engineer`,
`efficient-ai-engineering-workflow`) were also reviewed and not proposed: tiny persona prompts
with vague triggers, duplicates of each other, or pinned model versions that contradict the
"always latest" rule.

## 5. Compatibility, duplicates, conflicts

| Check | Result |
|---|---|
| Duplicates inside the proposed set | None. `smms-security-review` and `smms-tenant-isolation` are complementary |
| `conflicts_with` among the proposed set | None; no priority resolution needed (D-16) |
| Claude Code / OpenCode frontmatter | `name` = directory name, descriptions ≤ 376 chars (limits 1,536 / 1,024). OpenCode runtime: NOT TESTED |
| Name collisions in the target project | The same 8 names already exist unmanaged in SMMS `.claude/skills`; the sync blocks (R-12) until `--adopt` (identical bytes) or `--approve-overwrite` (the two `SOURCE.txt` files differ) |
| Personal-skill collisions | None at `~/.claude/skills/<id>`. The account has a synced `test-driven-development`, byte-identical to the proposal; the project copy wins and only the context cost is duplicated |
| Cross-skill references | `systematic-debugging` mentions `superpowers:verification-before-completion`, which is not in the set; advisory text only |
| Budget (D-14) | 8 of 40 descriptions. All 111 skills cost 54,671 characters (~13,667 tokens); the 8 cost 2,014 (~503), −96.3% **only if the other 103 are disabled in SMMS**, a separate decision (O-10) |

## 6. Staging dry run (scratch copy; reproducible)

Done with the real manager in a scratch copy of this repository and a scratch copy of SMMS
(neither the real library nor SMMS was changed): `add-skill` for each of the 8 from the
byte-verified sources (candidate, review pending) → `validate_catalog.py`: 0 errors →
approval **simulated in the scratch copy only** and the two packs added → `validate`: 0 errors
→ `select`: proposes `core` and nothing else → `sync` plan on the SMMS copy:

- as-is: **blocked** by R-12 (the 8 skills already exist unmanaged);
- with `--adopt` for all 8 and `--approve-overwrite` for the two upstream skills: **ready**,
  budget 0 → 8 of 40, 19 identical files adopted, 15 written, the 103 other skills untouched.

Applying was not attempted: it needs a person at a terminal (D-26), and this environment has
none.

## 7. Outcome (2026-10-31)

| Decision | Result |
|---|---|
| D-28 (O-16) | 8 skills imported as `candidate`; the 6 SMMS skills are `source.type: local` with `derived-from` SMMS `a21bfb8` (D-23) |
| D-29 (O-17) | `systematic-debugging` (obra/superpowers `c8921b5`, MIT) and `test-driven-development` (`b9e75dd`, MIT) are `active`, in the default `core` pack |
| D-30 (O-18) | The 6 SMMS skills were rewritten against the code of `claude/feature-program-1` and are version 1.1.0; they stay `candidate` / review pending in pack `smms-core` |
| D-31 (O-19) | Target `claude-code` only |

What changed in the six skills (all checked against code at `a21bfb8`; 163 cited paths exist):
Flyway replaces `init.sql` + `V2` as the migration mechanism (both profiles use `ddl-auto: validate`);
inventory, procurement, materials, assets, PM, workflow and notifications now exist; work-order
visibility is role-scoped by `WorkOrderAccessPolicy` (not only the technician); refresh tokens carry
`typ` and are refused as Bearer; login throttling is wired; uploads check magic bytes; passwords travel in a
JSON body; `<html dir="rtl">` is set at the root; the QA test plan is out of date and treated as hypotheses.
Previously reported "leads" that are fixed were removed; open questions were turned into checks.

Scratch trial (copy of SMMS, plan only, nothing written): `core` plan is blocked by R-12 (the two skills
exist unmanaged); `--adopt` is still blocked on the two `SOURCE.txt` files (they differ: the SMMS copies
cite `spruvex-r`, the library cites upstream); with `--approve-overwrite` for both the plan is
**ready** (0 to 2 of 40, 15 files overwritten, the other 109 skills untouched). Requesting `smms-core`
is refused (`inactive-skill-selected`) while its skills are candidates, which is the intended safeguard.

## 8. First real SMMS trial: remaining steps

1. Owner merges this PR (library commit becomes pinned; the plan uses the full commit SHA).
2. Owner reviews the six SMMS skills; each approved one is switched to `active` in a small PR
   (only then can `smms-core` be synchronized).
3. Owner decides O-15 (a terminal the owner controls, or another approval channel); applying is
   impossible from the iPhone / cloud session (D-26).
4. In SMMS, on a new branch (needs owner approval to touch SMMS): add `.tareq/skills.yaml`
   (`packs: [core]`, later `[core, smms-core]`, `targets: [claude-code]`) and run
   `tareq sync` with `--approve-overwrite` for the two general skills, review the plan, then `--apply`
   on the terminal. Review the diff in SMMS before merging it there.
5. O-10 (disable or merge the other 103 skills) is a separate later decision; until then the
   context cost does not drop.

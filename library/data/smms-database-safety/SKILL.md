---
name: smms-database-safety
description: Guards the SMMS PostgreSQL 16 schema, Flyway migrations, JPA enum mappings, transactions and backups. Use when touching entities, db/migration SQL, DataInitializer, docker-compose DB settings, or when running any query or backup against the SMMS database.
---

# SMMS database safety

Verified against `claude/feature-program-1` (a21bfb8). Paths are relative to the repository root; `SMMS` below means `Desktop/SMMS-FINAL`.

## When to use
Any change or review involving entities, enums, Flyway migrations, `ddl-auto`, transactional service code, indexes, backup/restore, or ad-hoc SQL against the running database.

## Inputs / scope
Branch/diff, and whether a live DB is reachable (container `smms_postgres`; database name and user come from `.env`; credentials are read by the container environment, never typed or printed).

## Relevant files
- `SMMS/backend-source/src/main/resources/db/migration/V1..V60` (Flyway; latest group V50-V60 notifications and tenant diagnostics)
- `SMMS/backend-source/src/main/resources/application.yml` (`spring.flyway`: baseline version 2, `clean-disabled: true`, `validate-on-migrate`, `out-of-order: false`)
- `application-prod.yml` and `application-dev.yml` (both `ddl-auto: validate`)
- `SMMS/scripts/init.sql` and `SMMS/scripts/V2__schema_migration.sql` (first-boot only; mounted by `docker-compose.yml` into `docker-entrypoint-initdb.d`)
- `SMMS/scripts/workflow_functions.sql` (applied only by `make migrate`; not mounted)
- `SMMS/scripts/backup-db.sh` (verified backup), `SMMS/Makefile` (`clean` runs `down -v`: FORBIDDEN)
- `SMMS/backend-source/src/main/java/com/smms/entity/`, `.../inventory/entity/`, `.../converter/TicketStatus*.java`
- `.../config/DataInitializer.java` (seed rows only), `TenantIntegrityReporter.java`
- `SMMS/docs/db-integration-tests.md` (opt-in `*DbIT` tests against a throwaway database)
- `SMMS/CLAUDE.md` section 2 (transaction rules)

## Procedure
1. **Two schema mechanisms.** A new database is created by `init.sql` + `V2` (entrypoint, only when the data volume is empty); Flyway then baselines it at version 2 and applies V3 and later. Every schema change for an existing database is a NEW additive `V<n>__*.sql` in `db/migration`. Never edit an applied migration (`validate-on-migrate` fails startup on a changed checksum). Never edit `init.sql` or `V2` to change a live DB. Version numbers are grouped by program wave (V10-V14, V20-V25, V30-V44, V50-V51, V60); check the highest existing number and the naming rules before adding one.
2. **ddl-auto.** Must be `validate` everywhere. Check `grep -rn "ddl-auto" SMMS/backend-source/src/main/resources SMMS/docker-compose*.yml`; `update`/`create` is Critical. Compose sets `SPRING_PROFILES_ACTIVE: prod`.
3. **Migration review.** Additive and re-runnable where possible (`IF NOT EXISTS`), constraints on large tables added `NOT VALID` then validated separately (see V13), no `DROP`/`TRUNCATE`/unscoped `UPDATE` on live data, a note on lock impact for plain `CREATE INDEX` on large tables (no migration uses `CONCURRENTLY`; it cannot run inside Flyway's transaction), a rollback note. Tenant-owned tables need `tenant_id` and an index (V4-V6, V10, V60 are the pattern).
4. **Enum mapping.** A Java enum bound to a native PG ENUM carries `@JdbcTypeCode(SqlTypes.NAMED_ENUM)`; `TicketStatus` uses `@Type(TicketStatusType.class)` because its DB values are lowercase. Compare Java constants to `CREATE TYPE ... AS ENUM` and later `ALTER TYPE ... ADD VALUE` in the migrations. A mismatch can fail at runtime, not at startup. Some columns are plain varchar with `@Enumerated(STRING)` (for example `Asset.criticality`); confirm which mechanism each column uses before changing it.
5. **DataInitializer.** It only inserts missing seed rows (default tenant, subscription, admin if absent, maintenance types) and must stay idempotent; schema and tenant backfills live in Flyway, and rows without a tenant are reported by `TenantIntegrityReporter` and fixed by an admin. Never delete or overwrite data in it. Do not print seeded credentials.
6. **Transaction rules (SMMS/CLAUDE.md section 2).** Parts plus status change in one `@Transactional`; stock checked before deduction; closing date not before opening date. Stock lives in `inventory/` (`StockLedgerService` methods are `Propagation.MANDATORY` and throw `InsufficientStockException`; `inventory_movements` is append-only by trigger, V34). Verify the caller opens the transaction; do not add `REQUIRES_NEW` around ledger calls.
7. **Triggers vs Hibernate.** `ticket_number` and `sla_deadline` are set by DB triggers; Hibernate does not re-read them after insert. Check code that uses them right after `save()`.
8. **Indexes.** Compare query predicates to indexes (`tenant_id`, `center_id`, `assigned_to_id`, `status`, SLA). Propose index changes as a new migration, never applied directly.
9. **Backups.** Use `bash SMMS/scripts/backup-db.sh`: `pg_dump -Fc` to `~/smms-backups/`, a restore rehearsal in a throwaway container, row-count comparison, and a `.verified` marker. `make backup` writes to `./backups/` (git-ignored) and is not verified. Restore only into a NEW scratch database after approval, never over the live one.
10. **Integration tests.** `*DbIT` tests run only with `SMMS_IT_DB_URL` pointing at a localhost database whose name starts with `smms_it`. Never point them at a project database.

Safe read-only queries (adjust container/db/user from `.env`):
```bash
docker exec smms_postgres psql -U "$DB_USER" -d "$DB_NAME" -c "\dt"
docker exec smms_postgres psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT version, description, success FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 5;"
docker exec smms_postgres psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT status, count(*) FROM work_orders GROUP BY 1;"
```
Never select `password_hash` or token columns.

## Expected output
| ID | Severity | File:line | Evidence | Recommendation | Verified? |
|----|----------|-----------|----------|----------------|-----------|
| DB-001 | Medium | path:line | what code/query shows | new additive migration or code fix | verified by query / code-reading only |

Add a short migration plan (SQL, rollback, who applies it) for schema work, marked "PROPOSED, needs approval".

## Verification
- `cd SMMS/backend-source && mvn -q test` (includes `MigrationScriptsTest`; `*DbIT` are skipped without a throwaway database).
- Schema vs entities: startup under `ddl-auto: validate` names the mismatch. Do not start or stop services unless asked.
- Record the SQL and the result count for any query.

## Safety restrictions
Read-only by default. FORBIDDEN without explicit written approval: `DROP`, `TRUNCATE`, `DELETE`/`UPDATE` without a reviewed WHERE, `ALTER` on live tables, editing an applied migration, Flyway `clean`/`repair`, `docker compose down -v`, `make clean`, deleting volumes, resetting or reseeding the DB. Never print or commit passwords, tokens, `.env` contents or dumps. Never make ports public (Postgres is bound to `127.0.0.1:5432`). No destructive or DoS testing. Never merge to main. Stop and ask before schema migrations or architectural changes. Distinguish PASS/FAIL/BLOCKED/NOT TESTED; never claim a feature exists without code evidence.

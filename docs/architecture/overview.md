# Architecture overview (M0)

Approved concepts only. Detailed schemas are defined in M1; adapter designs in M2.
Anything not listed here is not yet designed.

## Components

```
                ┌────────────────────────── tareq-skills (this repo) ───────────────────────────┐
                │ library/<category>/<skill>/   verbatim skill copies + SOURCE.txt              │
                │ catalog/skills.yaml           registry: category, source, version, status,    │
                │                               conflicts/replaces, context cost, license       │
                │ catalog/stacks.yaml           technology fingerprints                         │
                │ catalog/packs/                skill bundles (core, backend-java, ...)          │
                │ catalog/overlays/             activation tweaks without touching originals    │
                │ tareq-skill/ + bin/           manager: scan → select → sync / audit / doctor  │
                └───────────────────────────────────────────────────────────────────────────────┘
                                                  │
                         client project           ▼
                ┌───────────────────────────────────────────────────────────────────────────────┐
                │ .tareq/skills.yaml   chosen packs + extra skills                              │
                │ .tareq/skills.lock   resolved list, pinned commit per skill                   │
                │ generated adapters   Claude Code output, OpenCode output (never hand-edited)  │
                └───────────────────────────────────────────────────────────────────────────────┘
```

## Manager flow (approved intent, design in M3)

1. **Scan** — fingerprint the project (e.g. `pom.xml` → Java/Spring, `package.json` with
   `next`, Flyway/Postgres, Arabic/RTL).
2. **Select** — match packs to stacks and task type; resolve conflicts (order is open
   decision O-04); respect the context budget (O-02).
3. **Propose** — show the owner options with comparison and recommendation; record the
   decision in the project log.
4. **Sync** — write the lock file and generate adapter output.
5. **Audit / doctor / rollback** — conflicts and context cost, health checks, return to a
   previous lock.

## Client project files (owner requirement, §4-B; format in M3)

- **Skills register:** GitHub links for every skill used in the project, split into
  files by category (e.g. `SKILLS-<category>.md`).
- **Project log:** important instructions, changes, and steps taken.

## Context and token management (owner requirement, §4-C)

Save important state to in-project files (handoff / project log) and read them only when
needed; minimize token use. A skill cannot run `/compact` or switch the main session
model, so continuity relies on these files. Hook support for re-reading state is **unverified** (M2).

## Invariants

- Disabled skills are never deleted (status `disabled`).
- Every imported skill is pinned to a commit and has provenance in `SOURCE.txt`.
- No external script runs at import time.
- Adapter output is reproducible from manifest + lock.

## Known platform facts and limits

Verified facts about Claude Code skill loading (locations, frontmatter fields, name
precedence, symlinks) are recorded in §10-A of the original handoff and will be
completed in M2. OpenCode behavior is **unverified** (§10-B).

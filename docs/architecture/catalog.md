# Catalog data model and rules (M1)

Schemas: [`catalog/schema/`](../../catalog/schema/) (JSON Schema 2020-12).
Validator: `python3 bin/validate_catalog.py [--catalog DIR] [--project-dir DIR]`
(exit 1 on any error; warnings never fail). Tests: `python3 -m unittest discover -s tests -v`.
Dependencies: [`requirements.txt`](../../requirements.txt) (Python 3.10+, PyYAML, jsonschema — D-17).

## Files

| File | Schema | Purpose |
|---|---|---|
| `catalog/skills.yaml` | `skills.schema.json` | Declared `categories` + one metadata entry per skill |
| `catalog/stacks.yaml` | `stacks.schema.json` | Declarative technology detection |
| `catalog/packs/<id>.yaml` | `pack.schema.json` | Named skill bundles; file name = `id` |
| `catalog/overlays/<skill-id>.yaml` | `overlay.schema.json` | Activation metadata overrides; file name = skill id |
| `<project>/.tareq/skills.yaml` | `project-config.schema.json` | What a project asks for |
| `<project>/.tareq/skills.lock` | `lock.schema.json` | What was resolved, pinned, and hashed |

All YAML is loaded with a safe loader that also **rejects duplicate keys**.
IDs are kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`, ≤ 64 chars).

## Skill entry

| Field | Notes |
|---|---|
| `id`, `name` | Unique id; `name` is the skill's own declared name |
| `category` | Must be in `categories` |
| `path` | Must equal `library/<category>/<id>` — content stays separate from metadata |
| `scope` | `project` (requires `project`), `stack` (requires `stacks`), or `general` |
| `version` | Upstream tag or version of this copy |
| `source` | `type` `upstream` (requires `url` + 40-char `commit`) or `local`; `license` (SPDX id or `null`); `fetched_at`; `content_hash` (`sha256:`) |
| `license_exception` | Owner approval record (`approved_by`, `date`, `reason`) |
| `status` | `candidate` · `active` · `disabled` (disabled is never deleted) |
| `review` | `pending` · `approved` · `rejected`; approved/rejected need `reviewed_by` + `date` |
| `conflicts_with`, `replaces`, `requires` | Skill ids |
| `stacks` | Stack ids |
| `cost` | `description_chars`, `description_tokens_est` |
| `invocation` | `auto` (description always in context) or `manual` |
| `risk` | `level`; `offensive`; `isolated_env_only` |

## Validation rules

Error codes are stable; each is covered by a test in `tests/test_catalog.py`.

| Area | Rule | Code |
|---|---|---|
| Structure | Schema violation (types, enums, formats, unknown fields) | `schema` |
| | Duplicate skill / stack / pack id, or two overlays for one skill | `duplicate-id` |
| | Pack/overlay file name ≠ its id | `file-name` |
| | Category not declared; path ≠ `library/<category>/<id>` | `unknown-category`, `path-mismatch` |
| References | Unknown skill / stack / pack; self-reference | `unknown-skill`, `unknown-stack`, `unknown-pack`, `self-reference` |
| | `scope: stack` without stacks | `scope-stack-without-stacks` |
| Conflicts | Conflict declared on one side only | `asymmetric-conflict` |
| | Skill both requires and conflicts with another | `requires-conflict` |
| | Pack (incl. transitive includes) contains a conflicting pair | `pack-conflict` |
| Dependencies | Cycle in `requires`, stack `implies`, or pack `includes` | `requires-cycle`, `implies-cycle`, `pack-cycle` |
| | Active skill requires a non-active skill | `missing-dependency` |
| Status | Active without approved review | `active-unreviewed` |
| | Rejected but not disabled | `rejected-not-disabled` |
| | Active with a non-accepted or missing license and no exception | `license-not-accepted` |
| | Active offensive skill without `isolated_env_only: true` | `offensive-unrestricted` |
| | Skill and the skill it replaces both active | `replaced-still-active` |
| Packs | Disabled skill in a pack (error); candidate skill (warning) | `pack-disabled-skill`, `pack-candidate-skill` |
| | Default pack reaches a `marketing` skill | `default-pack-marketing` |
| Stacks | Invalid regex in `file_contains` | `bad-pattern` |

## License policy (D-15)

Accepted without exception: `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `0BSD`,
`ISC`. Any other or missing license keeps the skill `candidate`; activation requires a
recorded owner `license_exception`. Missing license information is never treated as
permission to use or redistribute.

## Technology detection

A stack matches when **any** rule in `detect.any` matches, and/or **all** rules in
`detect.all` match (both lists, when present, must be satisfied). Rule kinds, exactly
one per rule:

- `file: <glob>` — a matching path exists.
- `file_contains: {glob, pattern}` — a matching file contains the regex.
- `dependency: {ecosystem: npm|maven|gradle|pip, name}` — the project declares the dependency.

`implies` adds other stacks (no cycles). Evaluation is implemented in M3; M1 only defines
and validates the rules.

## Packs and overlays

- A pack lists skills and may `include` other packs (no cycles) and name triggering `stacks`.
- Packs default to `default: false`. No default pack may reach a `marketing` skill.
- Overlays change only `description`, `when_to_use`, `invocation`, `paths` for activation.
  They never modify `library/` files or catalog fields such as `status`, `license`, `path`.

## Project resolution (deterministic, not a selection engine)

1. Expand `packs` (with includes) + `include`, then remove `exclude`.
2. **Conflict priority (D-16):** `project` > `stack` > `general`. Across different levels the
   higher-priority skill wins and the other is dropped (reported as a warning).
   At the same level, validation fails (`unresolved-conflict`): the owner decides by
   excluding one. Recency, popularity, or license clarity never decide between different
   skills; "latest" applies only to versions of the same skill.
3. Every resolved skill must be `active` (`inactive-skill-selected`), belong to this project
   if project-scoped (`foreign-project-skill`), and have its `requires` resolved
   (`missing-dependency`).
4. **Budget (D-14):** auto-invoked descriptions (after overlays) must not exceed
   `budget.max_descriptions` (default 40) — a hard maximum, not a target
   (`budget-exceeded`). Selection always aims for the smallest suitable set.

Project config errors: `unknown-pack`, `unknown-skill`, `include-exclude-overlap`.

## Lock file and rollback design

The lock records: catalog repo + exact commit (+ optional tag), `config_hash` of
`.tareq/skills.yaml`, budget used/max, targets, every pack used with its file hash, and per
skill: version, source type/url/commit, `content_hash`, license, `via` (`include` or
`pack:<id>`), and `overlay_hash` when an overlay applies.

Validation against the catalog: `stale-lock` (config changed), `hash-mismatch`,
`commit-mismatch`, `overlay-mismatch`, `pack-mismatch`, `inactive-skill-selected`,
`unresolved-conflict`, `duplicate-id`, `budget-exceeded`, `project-mismatch`, `unpinned-source`.

Rollback = restore a previous committed lock (and the catalog commit it names); because
every input is pinned and hashed, the generated output is reproducible. Lock generation,
sync, and rollback commands are M3.

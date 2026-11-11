# Plan: Silastron PQC Tracker v1

Written after reading `Mehrn0ush/silastron-security-pulse`. Conventions borrowed
from Pulse: `src/` layout Python package, stdlib `unittest`, SHA-pinned actions
(same SHAs as Pulse), separate Collect and Publish workflows, fail-closed
collection, provenance shown on every page, same palette family and system fonts.

## Differences from Pulse (deliberate)
- Two small pinned runtime dependencies: PyYAML (the data files are YAML) and
  jsonschema (schema validation in CI/build). Everything else is stdlib.
- Static HTML is pre-rendered by a generator (`src/pqc_tracker/site.py`);
  JavaScript only adds filter/sort.
- Collect commits data to `main` (data is small); Publish builds from `main`.

## Layout
- `schemas/` JSON Schemas for implementations, standards, snapshot, changelog.
- `data/` human-edited YAML + machine-written JSON.
- `src/pqc_tracker/` collectors, changelog diff, validation, site generator.
- `tests/` unittest with recorded fixtures, no live network.
- `.github/workflows/` collect.yml, publish.yml, ci.yml.

## Rules enforced in code
1. A status other than `unverified`/`not-supported-unknown` needs `evidence_url` + `verified_on` (schema).
2. Collectors never touch YAML statuses. New release/draft revision => changelog entry + `review-needed` issue.
3. Collector error or malformed data => keep last snapshot, write nothing partial, exit non-zero; site shows "data stale since <date>".
4. Status changes in YAML are detected by diffing against the previously published `data/published-statuses.json` baseline.
5. No scores, no third-party assets, no analytics.

## Build order
1. Schemas + seed data (primary-source research, every claim fetched this session).
2. Collectors + tests. 3. Site generator + tests. 4. Workflows. 5. Docs/hygiene.
6. Full local build, inspect HTML with no JS, then push.

## Decisions made while building
- Hybrid key exchange column means TLS 1.3 groups; for OpenSSH it is SSH key exchange (noted on the row).
- Machine-collected release dates for projects without GitHub Releases are the tagged commit's date.
- `status-change` changelog entries are produced at publish time from the previously published
  `/data/statuses.json` and merged with the previously published changelog (Publish has read-only contents access).
- Publish also runs after a failed Collect so the "data stale since" notice appears while the last good snapshot is kept.
- A snapshot that lags the YAML (e.g. a newly added project) is not a validation error.

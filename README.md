# Silastron PQC Tracker

A post-quantum cryptography readiness tracker from [Silastron](https://silastron.com), published at
<https://pqc.silastron.com>. It answers two questions for engineers planning a PQC migration:

1. **Can I use PQC yet?** A matrix of crypto libraries and runtimes against ML-KEM (FIPS 203), ML-DSA (FIPS 204),
   SLH-DSA (FIPS 205) and hybrid key exchange.
2. **Where do the standards stand?** NIST standards and the relevant IETF documents, with a dated changelog.

Sibling project: [Silastron Security Pulse](https://pulse.silastron.com)
([repo](https://github.com/Mehrn0ush/silastron-security-pulse)). This repo follows its conventions: separate
Collect and Publish workflows, fail-closed collection, SHA-pinned actions, visible provenance.

## Principles

- **Evidence or "no statement found".** A support claim needs an evidence URL to a primary source that was read,
  tagged with its type and whether it is stated or inferred. Otherwise the cell says "no statement found" (with
  the sources searched) or "not checked". Source code alone never earns "supported".
- **Automation detects change; a person confirms meaning.** A new release or draft revision never changes a status.
  It adds a changelog entry and opens a `review-needed` issue.
- **Fail closed.** If a collector errors or returns malformed data, the last good snapshot is kept, the site shows
  "data stale since <date>", and the workflow fails. Partial data is never published.
- **No scores, grades or rankings.** Statuses only.
- **No tracking, cookies, analytics, third-party scripts, fonts or CDNs.**

## How it works

```
data/implementations.yaml  ─┐  human-edited statuses + evidence
data/standards.yaml        ─┤
data/snapshots/latest.json ─┤  machine-collected: latest release per project, latest revision/state per draft
data/changelog.json        ─┘  append-only, machine-detected entries
        │
        ▼  pqc-tracker build  (validate → render static HTML, JSON, Atom, sitemap)
   dist/site  ──►  GitHub Pages
```

| Workflow | Trigger | Permissions | What it does |
| --- | --- | --- | --- |
| `collect.yml` | daily + manual | contents: write, issues: write | Queries GitHub and the IETF Datatracker, writes the snapshot and changelog, opens `review-needed` issues (one per project; further changes become comments while one is open), commits the data. On failure it keeps the last snapshot and records the failure. |
| `publish.yml` | push to `main`, after each Collect, manual | contents: read, pages: write, id-token: write | Validates schemas, runs tests, downloads the previously published statuses to detect confirmed status changes, builds the site and deploys with the official Pages actions. |
| `ci.yml` | pull requests | contents: read | Lint, tests, schema validation, link check on evidence URLs, build. |

Status changes made by editing the YAML files are found at publish time by diffing against the previously published
build (`/data/statuses.json`), then merged with the previously published changelog so no entry is ever dropped.
See [docs/data.md](docs/data.md) for the data files and schemas.

## Run locally

Requires Python 3.12 or newer.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.lock && pip install --no-deps -e .

pqc-tracker validate                      # schema + semantic checks
python -m unittest discover -s tests      # tests, no network
pqc-tracker build --out dist/site         # render the site
python -m http.server 8080 --directory dist/site

# optional, uses the network
GITHUB_TOKEN=$(gh auth token) pqc-tracker collect
pqc-tracker check-links
```

## Correcting an entry

Edit `data/implementations.yaml` or `data/standards.yaml` with an evidence URL and today's `verified_on`, then open
a pull request, or open a "Status correction" issue. Details in [CONTRIBUTING.md](CONTRIBUTING.md).

## Repository layout

- `data/` statuses, snapshot, changelog
- `schemas/` JSON Schemas for all data files (also published at `/schemas/`)
- `src/pqc_tracker/` collectors, changelog logic, validation, site generator
- `tests/` unittest suite with recorded fixtures
- `docs/` plan and data documentation

## Licence

Code: [Apache-2.0](LICENSE). Data under `data/` and the published JSON: [CC BY 4.0](LICENSE-DATA.txt).
Linked sources keep their own licences; this project quotes only short factual phrases.

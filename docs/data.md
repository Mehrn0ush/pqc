# Data files

All files are validated against JSON Schemas in `schemas/` on every build and pull request. The same schemas are
published at <https://pqc.silastron.com/schemas/>. Data licence: CC BY 4.0.

## Human-edited

### `data/implementations.yaml`  (`implementations.schema.json`)

One entry per tracked project: `id`, `name`, `kind` (`library`, `runtime`, `protocol tool`), `homepage`, optional
`repo`, `release_source`, and `algorithms` with four claims: `mlkem`, `mldsa`, `slhdsa`, `hybrid_kex`.

Each claim has a `status`:

- `supported`, `experimental`, `planned`, `not-supported`: need `evidence_url`, `evidence_type`
  (`release-notes`, `official-docs`, `changelog`, `api-reference`, `source-code`, `issue-tracker`),
  `evidence_strength` (`stated` or `inferred`) and `verified_on`. `not-supported` is only for an explicit
  upstream statement. `planned` needs a maintainer's statement; an open request alone is not enough.
- `inferred` strength needs a one-line `strength_reason`. Source code alone never earns `supported`: a header or
  module with no statement of support level is at most `experimental`, with `source-code` evidence, `inferred`.
- `scope` (`standalone` or `hybrid-only`) is required for ML-KEM, ML-DSA and SLH-DSA cells that have a support
  status, and `hybrid-only` needs `scheme` (for example `X25519MLKEM768`). The `hybrid_kex` cell has no scope.
- `supported` and `experimental` need `since_version`, which may be `null` only with a `since_note` saying why.
  The site shows `null` as "version not stated".
- `no-statement-found`: we looked and found no primary source. Needs `checked_on` and `checked_sources` (every
  URL searched) and a `note`; an issue-tracker link goes in the note. It is never rendered as "not supported".
- `not-checked`: nobody has looked yet. No other fields.

`release_source` is one of `github_release` (latest non-prerelease GitHub release), `github_tags` (highest tag
matching `tag_regex` under `prefix`; date is the tagged commit's date) or `nss_release_notes` (the Mozilla NSS
release-notes index).

### `data/standards.yaml`  (`standards.schema.json`)

One entry per standard or draft: `id`, `title`, `body` (`NIST`, `IETF`), `status`, `status_date`, `source_url`,
`verified_on`, `note`. IETF entries also carry `group` and `datatracker_name`, which the collector uses; `rfc` is
required for `rfc-published`.

An `in-development` entry must record what NIST itself says: `stated_status` (NIST's wording), `stated_quote`
(a short quote), `stated_url` (the exact page), `checked_on` and `checked_sources` (the listings searched). Set
`no_draft_found: true` when those listings were searched for a draft publication and none was found; the site then
says "NIST's project page describes this as ... (checked <date>); no draft publication was found in <sources>".
URLs that return 404 are named in `note`, not listed as sources.

## Machine-written

### `data/snapshots/latest.json`  (`snapshot.schema.json`)

`releases[id] = {tag, published_at, url}` and `drafts[name] = {rev, state, iesg_state, rfc, updated_at, url}`.
Facts only. Replaced atomically; a failed run leaves it untouched.

### `data/changelog.json`  (`changelog.schema.json`)

Append-only list of entries. `kind` is `release`, `draft-revision`, `draft-state` (machine-detected,
`detected_by: machine`) or `status-change` (`detected_by: human`, `human_confirmed: true`). Entry ids are
deterministic hashes, so repeating a run adds nothing.

Machine entries are written by Collect. `status-change` entries are produced by Publish by comparing the YAML to
the previously published `/data/statuses.json`, and exist in the published `/data/changelog.json`, which is the
union of the repo file, the previously published file and the new entries.

### `data/collection-status.json`  (`collection-status.schema.json`)

`status` (`ok` or `failed`) and `last_good_collected_at` for the most recent Collect run. Drives the
"data stale since" notice, together with an age check of 72 hours.

## Published API

| URL | Content |
| --- | --- |
| `/data/latest.json` | Statuses, latest releases, standards with Datatracker state, freshness fields |
| `/data/changelog.json` | Full changelog, newest first |
| `/data/statuses.json` | Compact status map used as the baseline for the next build |
| `/feed.xml` | Atom feed of the latest 100 changelog entries |
| `/schemas/*.schema.json` | JSON Schemas |

`/data/latest.json` fields: `schema_version`, `license`, `generated_at`, `last_verified` (latest human check of
any entry), `last_collected`, `stale_since` (date or null), `algorithms`, `implementations[]`, `standards[]`.

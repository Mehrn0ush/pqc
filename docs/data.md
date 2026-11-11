# Data files

All files are validated against JSON Schemas in `schemas/` on every build and pull request. The same schemas are
published at <https://pqc.silastron.com/schemas/>. Data licence: CC BY 4.0.

## Human-edited

### `data/implementations.yaml`  (`implementations.schema.json`)

One entry per tracked project: `id`, `name`, `kind` (`library`, `runtime`, `protocol tool`), `homepage`, optional
`repo`, `release_source`, and `algorithms` with four claims: `mlkem`, `mldsa`, `slhdsa`, `hybrid_kex`.

Each claim: `status` (`supported`, `experimental`, `planned`, `not-supported`, `unverified`), `since_version`,
`evidence_url`, `verified_on` (ISO date), `note`. Any status other than `unverified` requires `evidence_url`.
An `unverified` claim cannot carry `since_version`.

`release_source` is one of `github_release` (latest non-prerelease GitHub release), `github_tags` (highest tag
matching `tag_regex` under `prefix`; date is the tagged commit's date) or `nss_release_notes` (the Mozilla NSS
release-notes index).

### `data/standards.yaml`  (`standards.schema.json`)

One entry per standard or draft: `id`, `title`, `body` (`NIST`, `IETF`), `status`, `status_date`, `source_url`,
`verified_on`, `note`. IETF entries also carry `group` and `datatracker_name`, which the collector uses; `rfc` is
required for `rfc-published`.

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

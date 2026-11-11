# Data files

All files are validated against JSON Schemas in `schemas/` on every build and pull request. The same schemas are
published at <https://pqc.silastron.com/schemas/>. Data licence: CC BY 4.0.

## Human-edited

### `data/implementations.yaml`  (`implementations.schema.json`)

One entry per tracked project: `id`, `name`, `kind` (`library`, `runtime`, `protocol tool`), `homepage`, optional
`repo`, `release_source`, and `algorithms` with four claims: `mlkem`, `mldsa`, `slhdsa`, `hybrid_kex`.

Each claim has a `status`:

- `supported`, `implemented-unstated`, `experimental`, `planned`, `not-supported`: need `evidence_url`,
  `evidence_type` (`release-notes`, `official-docs`, `changelog`, `api-reference`, `source-code`, `issue-tracker`,
  `first-party-deployment`),
  `evidence_strength` (`stated` or `inferred`) and `verified_on`. `not-supported` is only for an explicit
  upstream statement. `planned` needs a maintainer's statement; an open request alone is not enough.
- `inferred` strength needs a one-line `strength_reason`. Source code alone never earns `supported`: a header or
  module with no statement of support level is `implemented-unstated` ("Implemented, support level not stated"),
  with `source-code` evidence, `inferred`.
- `experimental` is only for a project that itself uses that word or an equivalent (preview, draft, unstable, not
  for production). `experimental_term` holds the term and the `note` must quote it in double quotes.
- `first-party-deployment`: the organisation that maintains the project says a product of its own ships the
  algorithm using it (Chromium for BoringSSL, Firefox release notes for NSS). Always `inferred`; the reason names
  the product and version.
- `planned` needs `statement_date` (the date of the maintainer's statement), `maintainer_basis` (`kind`:
  `maintainers-file`, `codeowners`, `org-membership`, `governance-page` or `commit-history`, which is shown
  as "commit history alone"; plus `detail` and optionally `url`) and optionally `statement_target_date`. The
  validator fails when the statement is more than 365 days old or the target date has passed, so the cell must
  be re-confirmed or changed to `no-statement-found` (with the old statement linked in the `note` as history).
  `pqc-tracker validate` warns 30 days before a cell expires.
- `scope` (`standalone` or `hybrid-only`) is required for ML-KEM, ML-DSA and SLH-DSA cells that have a support
  status, and `hybrid-only` needs `scheme` (for example `X25519MLKEM768`). The `hybrid_kex` cell has no scope.
- `supported` and `experimental` need `since_version`, which may be `null` only with a `since_note` saying why.
  The site shows `null` as "version not stated".
- `no-statement-found`: we looked and found no primary source. Needs `checked_on` and `checked_sources` (every
  URL searched) and a `note`; an issue-tracker link goes in the note. It is never rendered as "not supported".
- `not-checked`: nobody has looked yet. No other fields.

`release_source` is one of:

- `github_release`: latest non-prerelease GitHub release (`date_source: official`).
- `github_tags`: highest tag matching `tag_regex` under `prefix`; the date is the tagged commit's date
  (`date_source: tag-commit`, shown as "approximate"). Used only where no machine-readable official date exists
  (OpenJDK, whose release pages return 403 to automated clients).
- `go_release_history`, `botan_news`, `openssh_release_notes`, `bc_release_notes`, `nss_release_notes`: read the
  project's own release page (`url`); the date is the one the project publishes (`date_source: official`).
  The tag keeps the spelling the git tag would have so the changelog does not report a new release when only
  the source changes.

Each snapshot release records `date_source`. A page that changes shape fails the whole Collect run.

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
`detected_by: machine`), or `status-change` and `tracking-began` (`detected_by: human`, derived, never stored here). Entry ids are
deterministic hashes, so repeating a run adds nothing.

Machine entries are written by Collect. `status-change` entries are never stored in this file: Build derives them
from the git history (first-parent commits on `main`) of `data/implementations.yaml` and `data/standards.yaml`, one
entry per changed status, dated by the commit and keyed by its id.

`data/changelog_baseline.txt` holds the full SHA of a commit on `main` (comments start with `#`). Nothing before
that commit is published: its state is shown on `/changes/` as a single "Tracking began <date>" entry and only
later changes are listed. While the file names no commit, no confirmed status changes are published. A SHA that
does not exist or is not on the first-parent line of `main` fails the build. To set it, see below. The published `/data/changelog.json` is the union of this file and the derived entries. A shallow clone
fails the build, because it would silently drop history. Renamed statuses (`unverified` is now `not-checked`) are
normalised so a rename is not reported as a change.

### `data/collection-status.json`  (`collection-status.schema.json`)

`status` (`ok` or `failed`) and `last_good_collected_at` for the most recent Collect run. Drives the
"data stale since" notice, together with an age check of 72 hours.

### Setting the baseline

After the last pull request of the stack is merged, from an up-to-date `main`:

```bash
printf '# Status changes are published only from this commit onwards.\n%s\n' "$(git rev-parse HEAD)" > data/changelog_baseline.txt
git add data/changelog_baseline.txt && git commit -m "Set the changelog baseline" && git push
```

Use the merge commit of the last merged PR (a squash or rebase merge gives a different SHA; use whatever `HEAD`
is at that moment). Publish then builds with the baseline.

## Published API

| URL | Content |
| --- | --- |
| `/data/latest.json` | Statuses, latest releases, standards with Datatracker state, freshness fields |
| `/data/changelog.json` | Full changelog, newest first |
| `/feed.xml` | Atom feed of the latest 100 changelog entries |
| `/schemas/*.schema.json` | JSON Schemas |

`/data/latest.json` fields: `schema_version`, `license`, `generated_at`, `last_verified` (latest human check of
any entry), `last_collected`, `stale_since` (date or null), `algorithms`, `implementations[]`, `standards[]`.

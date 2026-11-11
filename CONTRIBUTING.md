# Contributing

## The evidence rule

**A project is never shown as supporting an algorithm unless the claim has an `evidence_url` pointing to a
primary source that you have read.** Primary sources are the project's own release notes, official
documentation, changelog, or public API headers. Blog posts, news articles, social media, issue comments,
and "I remember it did" are not evidence.

If you cannot confirm a claim, use `no-statement-found` and list every source you searched in
`checked_sources`, or leave it `not-checked`. "I found no mention" is not evidence of `not-supported`; that
status needs the project to say so. Source code alone is `implemented-unstated`; it never earns `supported`, and
`experimental` is only for a term the project itself uses (quote it in the note). A `planned` cell needs a
maintainer statement under 12 months old whose target has not passed, and a `maintainer_basis`. If you conclude support from
indirect evidence (a bug-fix title, a header), mark the cell `inferred` and give the reason.

## Correcting or adding a status

1. Open `data/implementations.yaml` (or `data/standards.yaml`).
2. Change `status`, `since_version`, `evidence_url`, `evidence_type`, `evidence_strength`, `verified_on`
   (today's date, `YYYY-MM-DD`) and `note`. See `docs/data.md` for the fields each status needs.
   Keep the note to a short factual phrase; do not paste text from the source.
3. Run the checks:

   ```bash
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements-dev.lock && pip install --no-deps -e .
   pqc-tracker validate
   python -m unittest discover -s tests
   ruff check . && ruff format --check .
   ```
4. Open a pull request linking the evidence. CI validates the schemas, runs the tests, builds the site and
   checks that evidence URLs resolve.

Don't have time for a pull request? Use the "Status correction" issue template.

## Automated "review-needed" issues

When a tracked project publishes a release or an IETF draft changes, the Collect workflow records the fact in
`data/changelog.json` and opens an issue labelled `review-needed`. It does not change any status. Read the
source, update the YAML if something changed (with evidence), and close the issue.

## Adding a project

Add an entry to `data/implementations.yaml` with all four algorithms. Anything not yet looked at is
`not-checked`. Choose a `release_source` (`github_release`, `github_tags` or `nss_release_notes`; the schema is
in `schemas/implementations.schema.json`). Adding a new source type means a collector and fixture-based tests
in `src/pqc_tracker/sources.py`.

## Rules for code

- No scores, grades or rankings of projects. Statuses only.
- No tracking, cookies, analytics, third-party scripts, fonts, CDNs or forms.
- Collectors fail closed: on any error, keep the last good snapshot and fail loudly.
- Tests must not use the network; record fixtures under `tests/fixtures/`.

## Licences

Code is Apache-2.0 (`LICENSE`). Data under `data/` is CC BY 4.0 (`LICENSE-DATA.txt`). By contributing you agree
your contribution is licensed the same way.

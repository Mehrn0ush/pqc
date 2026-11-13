# Porting the PQC Tracker hardening to Pulse

A hand-over for whoever works on the Pulse repo. I have not read the Pulse repo; everything about it below is
an assumption taken from this repo's README, which says it "follows its conventions: separate Collect and
Publish workflows, fail-closed collection, SHA-pinned actions, visible provenance". Check each assumption
before copying.

Source of truth in this repo: the `operations-hardening` pull request, `docs/operations.md`.

## 1. Decouple tests from live data and the clock: applies

Any suite that builds from the repo's committed data breaks the day Collect changes that data (it happened here:
two stale-notice tests expected the date of the real snapshot, and Publish failed on two consecutive days).

Port:
- A frozen fixture data tree for tests (`tests/fixtures/data`) and a loader.
- `tests/guard.py`, installed from `tests/__init__.py`: it patches `open` so a test that opens anything under
  `data/` fails, except inside one explicitly named context manager (`real_data_shape()`), which is for
  validation-only checks. Add a static test that no test file names the real data directory outside the helpers.
- One clock: a single `utcnow()` that honours a `PQC_NOW` environment variable; the suite sets it for the whole
  run; a static test that nothing else calls `datetime.now`, `date.today` or `time.time`.
- The CI matrix job (clock at now, +1, +45, +400 days, snapshot dated each of those). `fake_collection.py` edits
  the checkout's collection dates only.

What differs in Pulse:
- File names and the shape of the collected data (Pulse's snapshot is not `data/snapshots/latest.json`); change
  the guard's protected path list and `fake_collection.py` to match.
- If Pulse's code reads the clock in several places, route them through one function first; the guard test will
  list the stragglers.
- If Pulse has tests that assert on live feed content, they need recorded fixtures instead.
- The matrix runs the whole suite 4 x 4 times; if Pulse's suite is slow, shorten it or run the 4 clocks as a
  matrix and loop the snapshot dates inside one job (as here).

## 2. A Collect-triggered Publish must not be blocked by code tests: applies if Pulse's Publish runs tests

Port `publish-gate.sh` and the `gate` step. It skips the unit tests only for a `workflow_run` trigger when
`git diff --name-only <live commit> HEAD` shows nothing outside the data paths; every other trigger, and any doubt
(live commit unknown, not in the clone), runs them. This needs:
- a `/build.json`-style file on the live site that records the commit built (section 1 of the previous pass here:
  `buildinfo.py`, the footer link, the smoke test). **If Pulse has no build marker, port that first**; the gate
  has nothing to compare against without it and will always run the tests.
- `fetch-depth: 0` in the Publish checkout.

What differs: the list of paths that count as "data" (here `data/`; the gate excludes the pathspec `data/`),
and the name of the workflow that triggers Publish (here `Collect`).

## 3. Staleness the visitor can see without a rebuild: applies if Pulse is a static site

Port `stale.js` (under 1 KB, same origin, no inline code, `script-src 'self'` stays), the footer stamps
(`data-collected`, `data-built`), the repeated "collected <date>" beside the main heading, and the tests (Node's
`vm` with an injected `Date`).

What differs:
- Pulse may publish more often than daily; 48 hours is this site's threshold because it collects daily. Set it to
  a few times Pulse's collection interval.
- If Pulse's pages are not built by one `footer()` function, add the two attributes wherever the page footer is
  produced; the script only needs one element with `data-collected` and `data-built`.
- Pulse may already have a content-security-policy; check it allows a second same-origin script file.
- The notice text is fixed by the brief here; adjust it for Pulse's wording.

## 4. Alerts: applies

Port `watchdog.py`, `watchdog.yml`, the `site-stale` label and the tests. The decision logic is pure and has no
dependency on this project's data.

What differs:
- The live URL, and the file the watchdog reads (needs the build marker from section 2).
- "main's latest data commit": here `commits?path=data`. Use Pulse's data paths.
- Cron: every 6 hours here; match Pulse's freshness target.
- Thresholds: 48 hours old, 6 hours behind main, three failed fetches. Adjust to Pulse's schedule.
- The owner: `--owner` defaults to the repository owner; a personal repo can assign it, an organisation repo needs
  an assignable user or team lead.
- Workflow names in `workflow_run: workflows: [Collect, Publish]` must match Pulse's workflow names exactly.
- Permissions stay `issues: write`, `contents: read`.
- Scheduled workflows in a public repository are disabled after 60 days without repository activity (GitHub's
  documented rule): note it in Pulse's operations doc, as here.

## Also copy

- `docs/operations.md` structure (what runs when, alert meanings, three recovery runbooks, how to re-run Publish).
- The notification instruction (it is about the owner's GitHub account, not the repo).

## Not covered here

Sections 5 and 6 of this pass are documentation. The Collect push-with-retry script and the fetch-depth fix were
earlier passes; port them too if Pulse's Collect pushes directly to its default branch.

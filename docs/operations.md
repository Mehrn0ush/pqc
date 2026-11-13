# Operations

How the site is kept fresh, what the alerts mean, and what to do when something stops. Everything below can be
done from a browser or with the `gh` CLI; no repository setting needs to change.

## What runs when

| Workflow | Starts when | What it does | Writes |
| --- | --- | --- | --- |
| **Collect** (`collect.yml`) | daily at 06:17 UTC; by hand | Reads each project's release page and the IETF Datatracker, writes `data/snapshots/latest.json`, `data/changelog.json` and `data/collection-status.json`, opens `review-needed` issues (also for `planned` statements that expired or are about to). Fails closed: on any error the last good snapshot stays and `collection-status.json` records the failure. Pushes with fetch, rebase and up to three attempts. | commits to `main` (data files only), issues |
| **Publish** (`publish.yml`) | every push to `main`; after every completed Collect (success or failure); by hand | Validates the data, runs the unit tests (see below), builds the site, deploys it to GitHub Pages, then **smoke-tests** the live site: `/build.json` and `/data/latest.json` must match the build (commit, hash of `implementations.yaml`, every status). | the live site |
| **CI** (`ci.yml`) | every pull request; by hand | Lint, unit tests, schema validation, build, evidence-link check, Atom feed validation, and the clock matrix (the suite at clock = now, +1, +45 and +400 days, with the snapshot dated each of those). | nothing |
| **Watchdog** (`watchdog.yml`) | every 6 hours (at :23); after every Collect or Publish that **failed**; by hand | Checks that the live site is fresh and keeps one `site-stale` issue in step with the result. Independent of Collect and Publish. | issues only |

**Unit tests and Publish.** Tests gate every pull request and every push. A Publish that Collect started has not
changed any code, so it skips the unit tests when nothing outside `data/` differs from the commit that is live
(`.github/scripts/publish-gate.sh`); it still validates the data, builds and smoke-tests. If code differs from the
live commit, or the live commit cannot be read, the tests run. Tests never read `data/` or the wall clock
(`tests/guard.py`), so a Collect commit cannot break them.

**The site's own warnings.** The build adds a "data stale since <date>" notice when the last collection failed or
is more than 72 hours old. A small script (`/assets/stale.js`) adds a notice in the visitor's browser when the
page's collected time is more than 48 hours before the visitor's clock. Without JavaScript the footer and the
matrix heading show the collection date. The build-time notice only appears if Publish runs, which is why the
watchdog exists.

## The `site-stale` issue

One GitHub issue, labelled `site-stale` and assigned to the repository owner. While it is open the watchdog never
opens another; it adds a comment at most once a day while the problem lasts. It closes the issue itself, with a
comment, the next time the periodic check passes. A failed Collect or Publish run raises the issue immediately but
never closes it: only a passing periodic check does.

| Alert code | Raised when | Usually means |
| --- | --- | --- |
| `build-old` | the live `/build.json` says the site was built more than 48 hours ago | Publish has not succeeded for two days. Collect and Publish run daily, so something is failing, or Actions is disabled. |
| `behind-main` | `main`'s latest commit that touched `data/` is not in the live site and is more than 6 hours old | Collect committed data but Publish did not deploy it: a failed or cancelled Publish, a failed smoke test, or a Pages problem. |
| `fetch-failed` | the live `/build.json` or `/data/latest.json` could not be read three times in a row (30 seconds apart) | the site is down, the domain or DNS is broken, or Pages is unpublished. |
| `run-failed` | a Collect or Publish run finished with `failure` | the run named in the issue failed; the link is in the issue. |

## Recover from a failed Collect

1. Open the failed run from the issue (or **Actions → Collect**). Read the step that failed.
2. Typical causes:
   - *A project's release page changed shape* (the error names the project and parser). Fix the parser in
     `src/pqc_tracker/sources.py` and its fixture under `tests/fixtures/`; open a pull request. Nothing is
     published from a half-collected run: the last good snapshot stays live and the site says "data stale since".
   - *A network or rate-limit error.* Re-run: **Actions → Collect → Run workflow**. Tick **dry_run** first to see
     what it would change without committing anything or opening issues.
   - *The push was rejected* (`rebase ... conflicts` or `giving up after 3 attempts`). Someone changed a `data/`
     file at the same time. Re-run; if it conflicts again, look at the commits to `data/` since the run started.
     If `main` is protected, Collect cannot push: see "Protected main" below.
3. After a green Collect, Publish starts by itself. Confirm with "Check the live site" below.

## Recover from a failed Publish

1. Open the failed run and find the failing step.
   - **Validate schemas**: a data file is invalid. Fix `data/implementations.yaml` or `data/standards.yaml` in a
     pull request; the error lists every problem.
   - **Run tests**: only runs when code changed or the live commit is unknown. Fix the test or the code in a pull
     request. Merging that fix runs Publish again.
   - **Build site**: read the error (for example a shallow clone, or a baseline SHA that is not on `main`).
   - **Deploy to GitHub Pages**: usually transient; re-run the failed jobs.
   - **Check the live site serves this build**: the deploy finished but the live site still serves something
     else after five minutes. Re-run that job once; if it still fails, the difference is printed in the log.
2. Re-run by hand (see below). Publish always builds the latest `main`.

## Recover from a stale site

1. Compare what is live with `main`:

   ```bash
   curl -s "https://pqc.silastron.com/build.json?cb=$(date +%s)"          # commit and built_at
   git fetch origin && git log -1 --format='%H %cI' origin/main -- data/   # latest data commit
   gh run list --workflow Publish --limit 5
   gh run list --workflow Collect --limit 5
   ```
2. If Collect has not run for more than a day: **Actions → Collect → Run workflow**. If no workflow has run for
   60 days, scheduled workflows in a public repository are disabled automatically (GitHub's documented rule):
   re-enable them under **Actions**, then run Collect.
3. If Collect succeeded but Publish did not deploy: re-run Publish by hand.
4. If the site is down (`fetch-failed`): open the repository's **Settings → Pages** and check the custom domain
   and the last deployment; check `https://pqc.silastron.com/` from another network.
5. When the live `/build.json` shows today's date and the `main` commit, the watchdog closes the issue at its
   next check (within 6 hours), or close it yourself.

## Re-run Publish by hand

- Browser: **Actions → Publish → Run workflow**, branch `main`.
- CLI: `gh workflow run publish.yml --ref main`, then `gh run watch`.
- Re-running an old failed run (**Re-run failed jobs**) re-runs it with the same trigger; use **Run workflow** to
  publish the current `main`.

## Check the live site

```bash
curl -s "https://pqc.silastron.com/build.json?cb=$(date +%s)"
curl -s "https://pqc.silastron.com/data/latest.json?cb=$(date +%s)" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d['generated_at'], d['last_collected'], d['stale_since'])"
```

`commit` should equal `git rev-parse origin/main` after a code change, or contain `main`'s latest data commit
after a Collect. `pqc-tracker smoke-test --site-dir <dir>` runs the same comparison against a built directory.

## Protected main

Collect pushes `data/` commits straight to `main` with the workflow token. If a ruleset or branch protection
requires pull requests, that push fails and Collect goes red. GitHub's documentation lists who can be added to a
ruleset's bypass list (repository admins, the maintain or write role, teams, GitHub Apps and Dependabot) and does
not name the Actions token, so plan for a GitHub App with bypass, or leave `main` unprotected for `data/`.

## Notifications

The watchdog assigns its issue to the repository owner. GitHub subscribes you to anything you are assigned to.
For it to reach you, in <https://github.com/settings/notifications> make sure email is ticked for notifications
you receive from participating in or watching conversations, and that a default notification email address is
set; install GitHub Mobile and enable push notifications in the app for assigned issues. The first alert is a
good test: check the issue appears in your notifications inbox.

## Testing rules

- Tests use `tests/fixtures/data`, never `data/`; reading `data/` from a test fails unless it is wrapped in
  `tests.real_data.real_data_shape()`, which is for shape checks only.
- The suite always runs with `PQC_NOW` set, so `utcnow()` is injected; CI runs it at other days.

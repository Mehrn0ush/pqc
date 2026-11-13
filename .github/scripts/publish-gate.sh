#!/usr/bin/env bash
# Decide whether Publish must run the unit tests. Prints `run_tests=true` or `run_tests=false` on stdout (so
# the workflow can append it to $GITHUB_OUTPUT) and the reason on stderr.
#
#   usage: publish-gate.sh <github event name>
#
# Data validation, the build and the post-deploy smoke test always run. The unit tests gate every PR (ci.yml)
# and every push; they are skipped only for a Publish started by Collect when nothing but data/ has changed
# since the commit that is live, because then the code has not changed and a test that fails can only be a
# test that depends on data. If anything outside data/ differs from the live commit, or the live commit cannot
# be determined, the tests run.
#
# PQC_LIVE_COMMIT overrides the live commit (tests); PQC_LIVE_URL overrides the site address.
set -uo pipefail

event="${1:?usage: publish-gate.sh <event name>}"

if [ "$event" != "workflow_run" ]; then
  echo "event $event: code may have changed, the unit tests run" >&2
  echo "run_tests=true"
  exit 0
fi

live="${PQC_LIVE_COMMIT:-}"
if [ -z "$live" ]; then
  url="${PQC_LIVE_URL:-https://pqc.silastron.com}"
  live=$(curl -fsS --max-time 20 "$url/build.json?cb=$(date +%s)" 2>/dev/null |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"])' 2>/dev/null || true)
fi

if [ -z "$live" ] || ! git cat-file -e "${live}^{commit}" 2>/dev/null; then
  echo "workflow_run: cannot tell which commit is live (${live:-no answer}), the unit tests run" >&2
  echo "run_tests=true"
  exit 0
fi

code_changes=$(git diff --name-only "$live" HEAD -- . ':(exclude)data/' || true)
if [ -n "$code_changes" ]; then
  echo "workflow_run: code changed since the live commit ${live:0:7}, the unit tests run:" >&2
  echo "$code_changes" | sed 's/^/  /' >&2
  echo "run_tests=true"
else
  echo "workflow_run: only data/ changed since the live commit ${live:0:7}, the unit tests are skipped" >&2
  echo "run_tests=false"
fi

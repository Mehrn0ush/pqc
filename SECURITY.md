# Security policy

## Scope

This repository builds a static, read-only website. It collects no user data, runs no server code, and holds
no secrets beyond the workflow-scoped `GITHUB_TOKEN`.

Please report privately through GitHub:
<https://github.com/Mehrn0ush/pqc/security/advisories/new>

Things that count as security issues here: a workflow that could be abused to write outside `data/` or to
publish unreviewed content, a way to inject script into generated pages, a third-party resource loaded by the
site, or a dependency with a known vulnerability.

A wrong support status is not a security issue. Use the "Status correction" issue template instead.

## Design choices

- Workflows use least-privilege `permissions` and pin third-party actions to commit SHAs.
- Collectors only contact `api.github.com`, `datatracker.ietf.org` and `firefox-source-docs.mozilla.org` over HTTPS.
- All HTML output is escaped, and pages carry a strict Content-Security-Policy meta tag with no inline script or style.
- Automation never edits `data/implementations.yaml` or `data/standards.yaml`.

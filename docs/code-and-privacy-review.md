# Code and privacy review

Reviewed on 8 October 2026. Existing working-tree changes were retained. No real
database was migrated, no production service was contacted, and Git history was
not rewritten.

## Guidance and scope

This review applies relevant principles to the existing Flask architecture:
readability, focused responsibilities, shared validation, explicit ownership,
consistent transaction boundaries, and small, testable functions. Principles
require judgment; this is not a claim that every possible clean-code rule has
been mechanically applied.

Primary references:

- [PEP 8](https://peps.python.org/pep-0008/): naming, layout, and consistency.
- [PEP 20](https://peps.python.org/pep-0020/): readable, explicit, simple code.
- [Flask application factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/): isolated app setup and unbound extensions.
- [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/): CSRF, escaping, upload responses, cookies, and response headers.

## Changes

- Split factory configuration, extension initialization, blueprint registration,
  and template setup into focused functions. Move the home view into its own
  `main` blueprint, retaining existing endpoint names and URLs.
- Centralize browser version parsing and use the same version bounds as the API.
  Keep account-scoped filter queries in the application service.
- Move CSV import-report generation out of the HTTP route while preserving
  formula protection, review decisions, and original-source columns.
- Share profile field definitions between the route and service.
- Separate notification eligibility, claimed delivery, and SMTP outcomes. Use
  the shared transaction helper for preferences, unsubscribe, and outcomes.
  Preserve durable daily claims and at-most-once sending attempts.
- Remove email addresses, companies, and job titles from model representations.
  Avoid logging filesystem exception details during resume cleanup.
- Redact URL queries and unsubscribe tokens from Werkzeug/Gunicorn access logs,
  including Gunicorn's separate query, path, and referrer fields. Send
  `Referrer-Policy: same-origin` on successful HTML pages so HTTPS form
  submissions pass Flask-WTF's origin check without sending referrers to
  external sites. Other responses, including OAuth callback and download
  redirects, use `no-referrer`.
- Serve Bootstrap, icons, and Inter from local static files. Restrict scripts,
  fonts, and stylesheets to the app's origin. Preserve licenses and pinned asset
  provenance/checksums in `app/static/vendor/`. Inline chart styles remain
  allowed; OAuth form redirects retain the existing Google exception.
- Preserve existing application loggers when Alembic configures migration
  logging, so application diagnostics continue to work after an upgrade.

## Privacy findings

**Remaining personal information:** reachable Git commits contain a personal
author email address and author attribution. Anyone receiving the repository's
history can read them. This is separate from application responses and ignored
local files. Use a hosting-provider no-reply email for future public commits.
Removing prior attribution requires a coordinated history rewrite and cannot
remove copies already shared; this review does not rewrite commits.

**Addressed in application code:** unsubscribe URLs could enter ordinary access
logs; model representations included personal/application fields; resume cleanup
could log a private filesystem path; page assets made automatic requests to CDN
and font providers. The changes above reduce those exposures. They do not erase
old logs, cached deployments, or previously distributed repository copies.

**Repository scan:** inspected the current tracked and non-ignored files, 23
reachable commits, and 519 reachable Git objects before changes. Checked common
credential patterns and matches against nonempty local secret/password/token/key
settings without printing their values. No matches for current local secret
values were found in shareable files or reachable history. Credential-URL matches
were test fixtures, documentation placeholders, or an older Compose example with
development defaults. No real environment file, database, resume, or backup was
found in the reachable committed paths. Git and Docker exclusion tests cover
these private file categories. Pattern checks cannot detect every possible secret
or every form of personal text.

The final working-tree scan covered 171 shareable files and again found no matches
for current local secret values. Local environment values were not sent to the
online guidance or package-audit services.

**Access control:** existing tests check cross-account job views, changes,
resumes, exports, imports, source connections, API credentials, optional API
fields, community consent, and notification preferences. Community identity is
discoverable by exact handle; accepted friends may see private-profile activity.
Public profiles and job sharing are explicit settings. Shared posting links are
the supplied URLs, so users should avoid sharing a link containing private
application tokens. Google/Notion integrations and opted-in SMTP delivery still
send the data necessary for those requested features.

## Verification

Final checks on the local Python 3.12.4 environment:

- Full Python suite with `RUN_BROWSER_TESTS=1`: **328 passed, 9 skipped**. The
  skipped checks require a dedicated PostgreSQL test database. An upstream
  Flask-Login deprecation warning remains.
- Browser checks cover desktop/mobile workflows and navigation. The added
  privacy check verifies local asset requests, successful font loading, and
  working Bootstrap scripts. The mobile Overview screenshot was inspected.
- Ruff lint and formatting checks passed for the app, configuration, operations,
  tests, and migrations; 94 Python files were formatted consistently.
- Node reference-client suite: **5 passed**.
- `pip check` passed; audits of declared direct runtime packages and the installed
  environment found **no known vulnerabilities** after updating the virtualenv's
  outdated pip. Installed the already-declared timezone data and PostgreSQL
  driver dependencies that were missing/outdated locally.
- All nine vendored asset/license checksums and `git diff --check` passed.

Tests use fictional accounts, temporary databases with migrations, and temporary
uploads. Live hosting, reverse-proxy logs, existing server logs, real OAuth
accounts, SMTP delivery, and remote repository visibility were not audited.
These checks do not establish that an existing deployment has never leaked
information.

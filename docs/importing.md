# Import existing application trackers

Sign in and choose **Data tools → Import applications**, or open
`/imports`. Nothing is added until you confirm a reviewed preview.

## Sources

- Upload XLSX, historical XLS, OpenDocument ODS, CSV, TSV, delimited TXT, JSON,
  JSONL, or NDJSON. JSON accepts a list of objects or a list under `applications`,
  `records`, `jobs`, or `data`, including this tracker's JSON exports.
- Paste table cells copied from Google Sheets, Excel, or another table. Include
  column headers when available; tabs and common CSV delimiters are detected.
- Paste a Google Sheets share URL for a sheet accessible without signing in,
  or a published-to-web URL. The linked tab (`gid`) is respected.
- Choose **Google Sheets private access** to authorize a selected spreadsheet
  without changing its sharing permissions. File download/upload and copy/paste
  remain available when Google OAuth is unconfigured.
- For either Google Sheets source, optionally enter an exact cell selection such
  as `B4:N200`, including its headings. Source row numbers in the preview refer
  to the actual spreadsheet; the mapping screen's header setting is relative to
  the selected range. Selections allow at most 60 columns and 1,030 rows. Public
  Sheets exports are cropped locally within the 5 MB download limit; authorized
  Sheets requests fetch the exact range from the API.
- Choose **Notion database or data source**, paste its link/ID and a private
  Notion connection token, and share the database with that connection. The
  server uses Notion API version `2025-09-03` to discover database data sources
  and read their pages, with bounded pagination. Choose a data source on the
  mapping screen and map its properties just like spreadsheet columns. Common
  text, status/select, date, number, URL, email and phone properties are supported.
  Tokens for one-time imports stay in request memory and are never saved in a
  preview, browser session, or response.

Files are limited to 5 MB, 60 columns, 10 tabs, 1,000 data rows per selected tab,
30 title/header rows, and 5,000 total workbook rows. Expanded archive/data size is
bounded to 20 MB. Split larger trackers into smaller files. These limits protect
the import service from accidental huge sheets and malicious archives.

## Mapping and review

The importer detects likely headers within the first 30 rows. Choose a different
tab/header, or header `0` for a table without column names. Suggestions recognize
common names such as Role/Position, Employer/Organization, Stage, Date applied,
Recruiter email, and Job link, with conservative fuzzy matching and URL/email
sample detection. Suggestions run locally without sending records to an AI service.

Review each column's destination. Job title and company are required; each
destination can be used once. Ignored columns are excluded unless you choose to
preserve them in notes. Use **Update status choices after remapping** when changing
the status column, then translate any unfamiliar labels to tracker statuses.

Known status aliases such as Wishlist, Submitted, Phone screen, and Offer received
are suggested. Unknown labels are flagged instead of silently becoming Applied.
Blank statuses use your selected default, initially Shortlisted.

Excel date cells, ISO calendar dates, full English month names, and numeric dates
with a four-digit year are supported. A consistent unambiguous day/month order
can be suggested. Dates such as `06/10/2026` require you to choose day/month/year
or month/day/year if the source does not establish an order. Missing dates remain
unknown; the importer never invents an application date or year.

The preview shows ready rows, duplicates, and errors. The full review CSV contains
original cells as well as converted values so you can correct the source file.
Invalid rows block confirmation unless you explicitly choose to skip them.
The page displays the first 100 rows; the report includes every row.

Duplicate checks compare normalized title/company, job URL, and applied date
against active records in your account and earlier rows in the same import.
The default skips these likely duplicates. Select separate applications when
similar rows represent genuinely distinct applications. Existing records are
preserved: imports create new records, without overwriting matches or restoring
deleted records. Exports/imports are portable records, not a full database restore;
account credentials, resumes, public IDs, versions, sync mappings, historical
events, and creation timestamps are not restored.

Confirmation rechecks rows and duplicates under the account lock. All selected
valid records, status events and change-feed entries save in one transaction.
Failure rolls back the batch; repeated confirmation returns the same receipt.
Imported records immediately participate in normal edits, exports and device sync.

## Google configuration

Reuse the OAuth web client and `/auth/google/callback` described in
[Google login setup](google-login.md). Enable the **Google Sheets API** in that
Google Cloud project and configure the read-only Sheets consent scope when needed.
Ordinary Google signup/login continues requesting only `openid email`.

Private import separately requests
`https://www.googleapis.com/auth/spreadsheets.readonly`. This scope permits reading
Google Sheets across the chosen Google account; this app reads only the selected
spreadsheet/tab and makes no changes to Google files. Google classifies this as a
sensitive scope, so public deployment can require verification. See
[Google's scope guidance](https://developers.google.com/workspace/sheets/api/scopes).
Google's consent UI explains the requested access; users can decline and upload
or paste instead. No Drive access or background synchronization is requested.

Google authorization is bound to the signed-in tracker account and a short-lived
state/PKCE/nonce flow. It does not switch or link tracker accounts. The access token
exists only in the callback request while reading the selected sheet: no token,
refresh token, or provider profile is saved in a cookie, preview, or database.
The callback query is redacted from default access logs. Live Google verification
requires your configured client credentials and consent/API settings.

Public link requests use fixed Google export endpoints. Arbitrary URLs and
redirects to non-export hosts are rejected; private API requests never follow
redirects with authorization headers. Response sizes and network timeouts are
bounded. Reading a public link does not modify the sheet's sharing settings.

## Private previews and deployment

Migration `f70a93bd2158` adds the `import_batch` table without changing existing
accounts or applications. Back up an existing database, install the requirements,
run `flask --app run.py db upgrade`, and restart the application. Compose's startup
migrator also grants runtime DELETE on the preview table for cancellation/cleanup.

Draft contents stay server-side in the database and are accessible only to their
owner for 30 minutes. Confirmation immediately clears the source and options,
retaining only counts for replay protection for 24 hours. Cancellation deletes the
preview. Older private backups can still contain preview data.

Expired drafts/receipts are removed on visits to `/imports` and when creating a
new draft. For prompt cleanup during idle periods, schedule this command using
your host's task runner, for example every five minutes:

```text
flask --app run.py cleanup-imports
```

Use a private database and the repository's normal backup/log exclusions. Uploaded
source files are parsed in memory rather than retained on disk. Workbook formulas
are not executed; Excel uses cached formula results, so recalculate/export a sheet
if cached values are missing. XML entities, oversized archive expansion, unsafe
job links and ownership fields are rejected or excluded. Review CSV cells escape
spreadsheet formula prefixes. HTML previews escape cell contents.

Tests use fictional workbooks, real parsers, temporary migrated databases,
transaction failures/replays, and desktop/mobile Chromium. Google tests replace
provider transport and exercise real OAuth/token validation; no real Google account
is accessed during tests.

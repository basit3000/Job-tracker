# Connect and sync an external tracker

Sign in and choose **Data tools → Import & sync** (`/imports`).
Choose Google Sheets or Notion and **Keep connected for syncing**. Name the
connection and choose a sync frequency. Google Sheets offers shared-link or
private access within the same form. Existing connections are available through
**Manage connected sources** (`/sources`); **Connect a source** returns to the
shared setup form.
Sync pulls data into this tracker; it does not write to providers.

## Custom selections and mappings

For Sheets, paste a share link with the chosen tab's `gid`. Optionally select
exact cells with a bounded A1 range such as `B4:N200`, including the heading row.
Private access fetches that range using Google's read-only Sheets API. Public
exports are downloaded within 5 MB and cropped before row/column validation.

For Notion, create a private connection with **Read content** capability and
share your database with it. Enter its token in the password field and provide
the database link/ID, or choose **Data source ID** and copy that ID from Notion's
**Manage data sources** menu. Multi-source databases offer their data sources
as tabs on the mapping screen. The implementation pins API `2025-09-03`.

Review the selected tab/header, suggested field mappings, date order, custom
statuses and ignored-column handling. Confirm the preview to save the mapping.
Unknown statuses and ambiguous dates require review. Limits remain 1,000 data
rows and 60 columns per source, with bounded downloads and pagination.

For Sheets, select a **unique ID column** when possible. IDs must be nonempty,
unique, unchanged and at most 256 characters. They keep jobs linked when rows
move or titles change. The default identity combines title, company, URL and
applied date; changing those fields becomes a new application. Row positions
are never persistent identities. Notion uses permanent page IDs automatically.

## Later syncs and conflicts

**Sync now** fetches fresh data and opens a preview before saving. Confirmed
syncs share the existing account lock, validation, job-version, status-history
and change-feed path. Repeating a confirmation cannot duplicate applications.

Each mapped field is compared with its last accepted source value:

- If the tracker still has that value, the source's new value is applied.
- If both sides already agree, their baseline advances without another write.
- If only the tracker changed, its edit is retained.
- If both sides changed differently, the tracker value is preserved and the
  conflict is reported. Other fields can still update safely.

Resolve a conflict by making source and tracker agree, then sync again. Mapped
empty optional cells clear their fields; unmapped fields remain intact. An
unmapped status is only a creation default. Terminal statuses clear follow-up
dates using the existing tracker rules.

An exact existing account-owned job can be linked without overwriting it.
Ambiguous matches and duplicate IDs require review. Locally deleted jobs are
never resurrected. Removing a source row does not delete a tracker job. Changes
to source headings require **Review mapping**, preventing silent column shifts.

**Disconnect source** erases its credential, merge baselines and previews and
stops polling; tracker applications remain. Private Sheets offer **Reconnect
Google** for expired/revoked access. Replace a Notion token by disconnecting and
reconnecting. Changing a connection's range also requires a new connection.

## Private platform configuration

Private recurring sources require a separate, stable `SYNC_ENCRYPTION_KEY` in
the platform's private environment. Generate it once:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the key private and identical across workers/restarts. Fernet credentials
are bound to both user and connection ID. Losing/changing the key requires
reconnecting sources. Never commit credentials or databases. `.env.example`
leaves all credentials empty. One-time imports remain available without this key.

Private Sheets additionally need [Google OAuth setup](google-login.md) and the
Sheets API enabled. Explicit sync connections request `openid email
spreadsheets.readonly`, offline access and consent. Only an encrypted refresh
token is persisted; access/ID tokens stay in request memory. Ordinary sign-in
and one-time imports do not save Google tokens or request offline access.
Testing-mode/revocation policies may require reconnection. The existing
localhost callback works without a public hosting URL.

Notion uses each user's own read-capable token and needs no platform-wide Notion
credentials/callback. Credentials never appear in cookies, previews, reports,
responses or routine worker logs. Provider errors are sanitized. Requests use
fixed HTTPS API hosts, bounded bodies/timeouts and disabled credential redirects.

Apply tracked schema migrations, then update runtime grants when using separate
PostgreSQL roles:

```powershell
flask --app run.py db upgrade
# Use the migrator role for role-separated deployments:
flask --app run.py grant-runtime
```

## Automatic syncing

Automatic syncing is off by default. Users can choose every 15 minutes or hourly,
and pause it by selecting manual syncing. A confirmed mapping is required.
Automatic runs use the same conflict-preserving merge. Invalid rows block the
whole run unless skipping them was explicitly enabled in the saved mapping.
Automatic source payloads are erased on success or failure; only aggregate
last-result counts, sanitized errors and needed merge baselines remain.

`python run.py` starts a background worker for local development (excluding the
debug reloader's parent). Docker Compose includes a dedicated `source_sync`
service using the runtime database role. Other deployments can run a separate
worker or periodically invoke the one-shot command:

```powershell
flask --app run.py sync-sources --watch
# Or invoke periodically through the deployment's own scheduler:
flask --app run.py sync-sources
```

Workers poll every 30 seconds, claim due sources under the account lock, fetch
outside the write lock and reject stale source versions. Overlapping workers
cannot apply the same preview twice. Each polling batch is limited to 20 sources.
Failures wait until the next interval; changed headings need mapping review and
revoked credentials need reconnection. No external scheduler is created by this
feature; the application worker handles users' selected intervals.

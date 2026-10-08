# Notifications

The header bell opens a private inbox at `/notifications`, with an unread count,
All/Unread filters, read/unread actions, dismiss, and mark-all-read. Opening a
notification marks it as read and goes to People, Follow-ups, Import & sync, or
Add application. The count refreshes every minute while the page is visible.

Use **Notification settings** in the inbox or Account menu to choose channels:

| Category | Trigger | In-app default | Email default |
| --- | --- | --- | --- |
| People | A new friend request or acceptance | On | Off |
| Follow-ups | One summary of due/overdue items per UTC day | On | Off |
| Import & sync | First failure of an automatic sync; resets after recovery | On | Off |
| Daily application reminder | No submitted application on the selected local date | Off | Off |

Existing daily email opt-ins are preserved by the migration. New email categories
always default to off. Channels are independent; email-only preferences are
supported. Changes affect future events, and turning an email category off also
cancels its queued emails. Existing inbox items remain available until dismissed.
Friend requests are never automatically accepted through a notification.

Daily nudges default to 20:00 UTC. Users choose an IANA time zone and hour. Checks
run from that hour until local midnight. Shortlisted/skipped jobs and unknown
application dates do not suppress nudges. Closed applications count only when
dated. Activity charts, streaks and follow-up dates continue to use UTC. Reminder
eligibility uses the selected local date, comparing application dates as recorded.

## Configure delivery

Apply the migration before restarting web and workers:

```powershell
.\.venv\Scripts\python.exe -m flask --app run.py db upgrade
```

On deployments with separate PostgreSQL schema-owner and runtime roles, run the
migration as the owner and re-run `flask --app wsgi.py grant-runtime` to grant
access to the new notification table. The release script supports this via
`GRANT_RUNTIME_ROLE=true`.

Set these environment variables (see `.env.example`):

```dotenv
EMAIL_REMINDERS_ENABLED=true
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=notifications@your-domain.example
APP_BASE_URL=https://your-tracker.example
```

`EMAIL_REMINDERS_ENABLED` is the existing global switch and now controls all
notification emails. Use your provider's verified sender and SMTP credentials.
`SMTP_SECURITY=ssl` supports implicit TLS, typically port 465. Unencrypted SMTP is
not supported. `APP_BASE_URL` must be the public HTTPS origin without a path;
loopback HTTP is allowed for local development. Web and workers need the same
database, settings and `SECRET_KEY`. Credentials never enter notification records.

## Run the worker

`python run.py` starts the development notification and source workers once, with
a debug-reloader guard. For production or `flask run`, run a separate worker:

```powershell
.\.venv\Scripts\python.exe -m flask --app run.py process-notifications --watch
```

Docker Compose's `reminders` service and `ops/railway-reminders.json` use this
command. Rebuild/restart web and worker after migration. The worker creates
scheduled in-app updates even without SMTP. Alternatively schedule
`flask --app wsgi.py process-notifications` every minute in an external worker.
It scans accounts in pages of 100 and attempts up to 100 notification emails and
100 daily reminder emails per run. Subsequent runs drain the remaining queue.

Home, inbox and unread-count requests also refresh that user's scheduled in-app
notifications. SMTP never runs in ordinary user requests. For Vercel, use an
external worker for the full notification cycle; `/internal/cron/reminders`
remains the bounded, legacy daily-email-only endpoint. The old CLI
`send-reminders --watch` uses the full notification cycle for compatibility;
one-shot `send-reminders` still sends only daily nudges.

## Delivery and consent

- Each recipient/event key is unique. Daily summaries and nudges do not repeat
  when pages reload or workers run concurrently.
- Email requires explicit opt-in at event creation and immediately before
  sending. Enabling email later does not email older in-app events.
- Workers durably claim an email before SMTP. Concurrent workers cannot send the
  same item twice. Uncertain or failed attempts are not automatically retried;
  history labels them as unconfirmed. SMTP acceptance is not proof of delivery.
- Notification email queued for over 24 hours is skipped. Follow-up summaries
  also expire at the end of their UTC date. Daily reminders have no catch-up.
- Email history and inbox contents are scoped to the signed-in user. Social
  emails contain the requesting/accepting person's display name. Emails include
  no private job records, resume attachments, source names or provider errors.
- Every email has a signed unsubscribe link. GET shows a confirmation so mail
  scanners cannot unsubscribe users; a CSRF-protected POST disables all email
  categories without login, leaving in-app preferences unchanged. Opting back
  into any email category rotates the key, invalidating older links. Links expire
  after 90 days; signed-in users can always change settings.
- Daily reminder deduplication uses local dates and IANA daylight-saving rules,
  rather than a rolling 24-hour interval.

Set `EMAIL_REMINDERS_ENABLED=false` to stop all sending. In-app notifications keep
working. Settings show when email is waiting for administrator configuration.

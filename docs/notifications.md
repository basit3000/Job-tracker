# Application reminders

Users can opt in under **Account → Notifications** or **Overview → Set a reminder**. Preferences default to off, 20:00, UTC. Users choose an IANA time zone and hour. The worker checks each minute from that hour until local midnight and skips anyone with a non-deleted submitted application dated that day. Shortlisted/skipped jobs and unknown dates do not suppress reminders. Closed applications count only when dated. The worker never sends catch-up emails for previous dates.

Activity charts and community streaks continue to use UTC calendar dates. Reminder eligibility uses the user's selected local date; dates are explicitly labeled in the UI. Since application dates have no time-of-day, they are compared as recorded, not converted from timestamps.

## Configure delivery

Apply migrations with `flask --app run.py db upgrade`. Set these environment variables (see `.env.example`):

```dotenv
EMAIL_REMINDERS_ENABLED=true
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-smtp-username
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=reminders@your-domain.example
APP_BASE_URL=https://your-tracker.example
```

Use your provider's verified sender and SMTP credentials. `SMTP_SECURITY=ssl` supports implicit TLS (typically port 465). Unencrypted SMTP is not supported. `APP_BASE_URL` must be the application's public HTTPS origin, without a path; loopback HTTP is allowed for local development. Both web and worker processes need the same database, configuration and `SECRET_KEY`. No credentials are stored in user preferences or logged. Python's [SMTP client](https://docs.python.org/3/library/smtplib.html) verifies TLS certificates; [tzdata](https://docs.python.org/3/library/zoneinfo.html) supplies time zones on Windows.

For local development or a standalone deployment, keep this command running alongside the web server:

```powershell
.\venv\Scripts\python.exe -m flask --app run.py send-reminders --watch
```

Docker Compose includes a `reminders` worker; rebuild/restart it and the web service after changing configuration. It remains idle while email delivery is disabled. Alternatively schedule `flask --app run.py send-reminders` every minute using cron or Windows Task Scheduler. A one-shot invocation reports an error for incomplete configuration. No scheduler runs inside request handlers or Flask's debug reloader.

## Delivery and consent

- A database unique constraint reserves each user/local-date combination before SMTP, preventing concurrent workers or restarts from repeating an attempt.
- Consent and recorded activity are checked again after the claim, immediately before sending. An email already handed to SMTP cannot be recalled.
- SMTP acceptance is reported as **Sent to email provider**, not proof of inbox delivery. Timeouts or crashes can leave delivery uncertain. Those attempts are not automatically retried that date to avoid duplicates; a future day is eligible as normal. A crashed worker's claim appears as pending or unconfirmed in history.
- The history is private to the signed-in user. Emails contain no job details, social activity, or attachments.
- Every reminder includes an expiring signed unsubscribe link. GET displays a confirmation to avoid mail scanners unsubscribing users; a CSRF-protected POST turns reminders off without requiring login. Turning reminders back on rotates the link key so older emails cannot disable a fresh opt-in. Links expire after 90 days; signed-in users can always disable reminders in settings.
- Time-zone changes can change the local date. The guarantee is one attempt per local date, not one per rolling 24-hour window. Daylight-saving changes use IANA zone rules; a skipped hour becomes due at the next poll, and a repeated hour does not repeat delivery.

Set `EMAIL_REMINDERS_ENABLED=false` to stop future sending globally. Users can save preferences before SMTP is configured; the page clearly displays that delivery is waiting for setup. This feature does not send mail until both administrator configuration and user opt-in are present.

# Cloud deployment

This app has provider configuration for Railway and Vercel. Both use the existing
Flask app factory and Alembic migrations. No hosting account, database, bucket,
or production secret is created by these files.

## Choose a runtime

| Capability | Railway / Docker | Vercel |
| --- | --- | --- |
| Web app | Gunicorn on the platform's `PORT` | Native Flask function, `wsgi.py` |
| Database | Managed PostgreSQL | External managed PostgreSQL |
| Rate limits | Shared Redis | External shared Redis, using a Redis protocol URL |
| Private resumes | Private S3-compatible bucket or attached volume | Private S3-compatible bucket |
| Static assets | Flask serves `app/static` | Build copies `app/static` to CDN `public/static` |
| Continuous syncing / reminders | Separate polling worker services | External workers or authenticated cron calls |
| Request limit | 5 MiB | 4 MiB, including multipart/form overhead |
| Migrations | Pre-deploy command | Separate release command, before deployment |

Railway is the recommended choice for the complete app with continuous polling.
Vercel can serve the app, but does not run the development server's threads or
the CLI's `--watch` workers. Its function payload limit is 4.5 MB; the app uses
a lower 4 MiB request limit. [Vercel limits](https://vercel.com/docs/functions/limitations)

The code remains compatible with Python 3.11 for Docker. Vercel's current Python
runtime starts at 3.12, so `.python-version` selects 3.12 there.
[Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)

## Environment variables

Enter real values in the provider's private environment settings. `.env.example`
is a local development template; its HTTP URLs and insecure-cookie setting must
be changed for production. Vercel and Railway activate production validation
automatically. Other hosts should set `APP_ENV=production`.

| Variable | Production value |
| --- | --- |
| `SECRET_KEY` | Private random value, at least 32 characters; stable across workers and redeploys |
| `DATABASE_URL` | PostgreSQL runtime connection URL; use the provider's pooling URL on Vercel and required TLS options for public connections |
| `RATELIMIT_STORAGE_URI` | `redis://` on a private network or `rediss://` for a public TLS endpoint; an HTTPS REST endpoint is not supported |
| `APP_BASE_URL` | Your public HTTPS origin, without a path |
| `SESSION_COOKIE_SECURE` | `true` (also defaults to true on hosted production) |
| `FLASK_DEBUG` | `false` |
| `ALLOW_INSECURE_LOCAL_API` | `false` |
| `UPLOAD_STORAGE` | `s3`, or `filesystem` with an attached persistent volume on a container host |
| `S3_BUCKET` | Private bucket's S3 API name |
| `S3_ENDPOINT_URL` | HTTPS S3-compatible base endpoint; leave unset for AWS S3 |
| `S3_REGION` | Region from the bucket provider; Railway/R2 commonly use `auto` |
| `S3_ADDRESSING_STYLE` | `virtual` by default; use `path` only if the provider requires it |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Bucket credentials; omit both when an AWS IAM role supplies credentials |
| `CRON_SECRET` | Separate random value of at least 32 characters for HTTP maintenance hooks |
| `MIGRATION_DATABASE_URL` | Optional schema-owner connection for the release command; never needed by web/worker services |
| `GRANT_RUNTIME_ROLE` | `true` only when you provisioned this repository's `tracker_runtime` role; defaults to `false` on managed hosts |
| `SYNC_ENCRYPTION_KEY` | Stable Fernet key if connecting private Google Sheets/Notion sources |
| `PUBLIC_SIGNUP_ENABLED` | `true` for registration, `false` for administrator-created accounts |

Generate signing keys locally with `python -c "import secrets;
print(secrets.token_hex(32))"`, using a separate value for each purpose. Keep
them outside Git. Optional Google login and SMTP settings are described in
[Google login](google-login.md) and [email reminders](notifications.md).
The default Google callback follows `APP_BASE_URL`; register its exact
`/auth/google/callback` URL with Google. An explicit `GOOGLE_REDIRECT_URI`
overrides that default.

Production startup rejects SQLite, in-memory rate limiting, HTTP public URLs,
debug mode, insecure cookies, and filesystem storage without an explicitly
configured volume path. Configuration errors identify variable names without
printing credentials. PostgreSQL connections use pre-ping; Vercel uses NullPool
so idle function instances do not retain their own connection pool.

## Railway

1. Create a project with PostgreSQL, Redis, and a private storage bucket. Connect
   this Git repository as the web service, with the repository root as its root
   directory and `/railway.json` as its config file.
2. Add the variables above. Reference the database service's `DATABASE_URL` and
   Redis service's `REDIS_URL` instead of copying passwords into config files.
   Set `APP_BASE_URL` to the generated/custom HTTPS domain and
   `WEB_CONCURRENCY=2` initially. Railway supplies `PORT`.
3. For a bucket named `Resumes`, map its variables in the web service:

   ```text
   UPLOAD_STORAGE=s3
   S3_BUCKET=${{Resumes.BUCKET}}
   S3_ENDPOINT_URL=${{Resumes.ENDPOINT}}
   S3_REGION=${{Resumes.REGION}}
   S3_ACCESS_KEY_ID=${{Resumes.ACCESS_KEY_ID}}
   S3_SECRET_ACCESS_KEY=${{Resumes.SECRET_ACCESS_KEY}}
   ```

   Use the actual service name. New Railway buckets use virtual-host addressing;
   older buckets may need `S3_ADDRESSING_STYLE=path`, as shown by their credentials
   screen. [Railway buckets](https://docs.railway.com/storage-buckets)
4. Deploy the web service. `railway.json` selects the Dockerfile, runs
   `python ops/migrate.py` before startup, starts Gunicorn without rerunning
   migrations, and checks `/healthz`. Pre-deploy migration setup uses a temporary
   directory because the upload volume is not mounted in that phase.
   [Railway pre-deploy commands](https://docs.railway.com/deployments/pre-deploy-command)
5. For source polling, create a second service from the same repo and set its
   config file to `/ops/railway-sources.json`. For reminders, use
   `/ops/railway-reminders.json`. Deploy these after the web migration succeeds.
   Supply the same runtime database, signing/encryption keys, Redis, public URL,
   and storage settings. Configure SMTP and enable emails on the web and reminder
   services so the settings page also reports delivery as configured. The source
   worker can leave email disabled. Do not give workers `MIGRATION_DATABASE_URL`
   or a public
   domain. Worker configs have no web healthcheck or migration command.
6. Create a daily cleanup service from the same repo with its config file set to
   `/ops/railway-cleanup.json` and the same runtime settings. It runs
   `flask --app wsgi.py cleanup-imports` at `0 3 * * *` UTC, without a healthcheck
   or pre-deploy migration, and exits after completing its work.

If using filesystem storage instead, attach a volume at `/app/uploads` and set
`UPLOAD_STORAGE=filesystem` and `UPLOAD_FOLDER=/app/uploads`. The app cannot
verify that a mount is persistent; attaching and backing up the volume remains
an operator responsibility. Use a private bucket for multiple web replicas or
deployments sharing resume files. Do not use a container's unmounted filesystem.

Railway's managed ingress supplies HTTPS protocol and client-IP headers. The app
trusts one protocol header and uses its `X-Real-IP` for rate limiting only when
the Railway platform environment is present. Custom proxy setups must configure
their own trusted headers. [Railway ingress](https://docs.railway.com/networking/public-networking/specs-and-limits)

## Vercel

1. Provision managed PostgreSQL, shared Redis, and a private S3-compatible bucket
   reachable from Vercel. Configure the variables above in the project. Private
   `*.railway.internal` URLs cannot be used by a Vercel function; use providers'
   public TLS connection endpoints. Keep preview environments on separate test
   databases/buckets/keys from production.
2. Import the repository using the Flask framework preset and root directory.
   `pyproject.toml` declares the runtime dependencies and selects `wsgi:app`;
   `uv.lock` pins their resolved dependencies. Keep runtime pins in
   `requirements.txt` aligned when updating them, then run `uv lock` with Python
   3.12 before committing. `vercel.json` configures a 300-second
   function duration. Enable Fluid compute and ensure your plan supports this
   duration. The build script publishes only public static assets, preserving
   existing `/static/...` URLs. `.vercelignore` excludes local environments,
   private databases, backups, uploads, and secrets from CLI uploads. Additional
   function exclusions protect the deployed bundle.
   [Native Flask deployment](https://vercel.com/docs/frameworks/backend/flask)
3. Before activating a deployment, apply migrations once from a trusted release
   environment with private variables set:

   ```bash
   pip install -r requirements.txt
   python ops/migrate.py
   ```

   The function never migrates during imports or requests. For later changes,
   serialize migrations and use changes compatible with the currently running
   release. Back up the database first; rollback of app code does not roll back
   database changes. Schema-owner credentials belong in the release environment,
   not Vercel's function variables.
4. Deploy using the connected Git integration or `vercel --prod`, then verify
   `/healthz`, login, `/static/css/styles.css`, upload/download, and record access
   with two different accounts. Use the actual CSS path present in `app/static`
   if renamed. Account bootstrap is available from a trusted release environment:
   `flask --app wsgi.py create-user`.
5. `vercel.json` schedules daily cleanup at `0 3 * * *` UTC. Set `CRON_SECRET` so
   Vercel supplies the expected bearer authorization automatically. Without it,
   maintenance returns 401. No secret is accepted in a URL/query parameter.
   [Vercel cron authentication](https://vercel.com/docs/cron-jobs/manage-cron-jobs)

The optional `/internal/cron/sources` endpoint processes at most one due source,
and `/internal/cron/reminders` attempts at most ten due messages. They use the
same durable claims as polling workers. Repeated calls continue outstanding work
without repeating a claimed daily reminder. Use `Authorization: Bearer
<CRON_SECRET>` from an external scheduler, or add those paths to Vercel cron
configuration on a plan supporting frequent schedules. Do not put that header
value in command history, logs, or committed files.

Vercel Hobby cron runs at most daily and may run within an hour of its scheduled
time. A daily poll cannot honor every user's local reminder hour or short source
sync intervals. For frequent polling, use paid scheduling or run the existing CLI
workers on a container host. Large source imports can exceed a function timeout
even with one source per call; run those through continuous workers. Cron jobs
are best effort, and monitoring must catch failed/missed runs.
[Vercel scheduling limits](https://vercel.com/docs/cron-jobs/manage-cron-jobs)

## Private storage and existing data

Keep the bucket private with public access blocked. Give its runtime principal
only Put/Get/Head/Delete permissions for this application's `resumes/` prefix.
No public ACL is requested. Names stay opaque UUID basenames in the database;
original resume names are not sent to the bucket. Downloads first authorize the
record owner, then redirect to a signed object URL valid for 60 seconds. That URL
is a temporary bearer capability: anyone receiving it can download the object
until it expires. Download responses are private/no-store with no-referrer.
Do not log response `Location` headers or share download URLs.
[S3 signed downloads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html)

Changing storage backends does not transfer existing files. Copy existing resume
files to the private bucket under `resumes/<unchanged resume_filename>` using the
provider's authenticated tools, verify downloads, and retain a private backup.
Provisioning a fresh PostgreSQL database also does not transfer local SQLite
accounts, application data or credentials. Plan and verify a separate data
migration, or start with a fresh database and use the app's reviewed per-account
record import. Always apply schema changes with Flask-Migrate.

## Other container hosts

Use the included Dockerfile, shared PostgreSQL/Redis, and durable resume storage.
Set `APP_ENV=production`. Run `python ops/migrate.py` as the release/pre-deploy
command and `python ops/serve.py --skip-migrations` as the start command. If your
host has no release phase, a single initial web instance can use
`python ops/serve.py`; avoid simultaneous startup migrations from replicas.
`PORT` defaults to 5000 when the platform does not supply it.

For a custom ingress, configure `PROXY_PROTO_COUNT` and `PROXY_FOR_COUNT` only
after verifying the exact proxy chain and that clients cannot reach the app
directly or inject trusted header values. Host, port, and prefix headers are not
trusted by default. Managed Vercel/Railway use their own client-IP header;
generic servers use the remote address after any explicitly configured proxy
middleware. [Flask proxy configuration](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/)

After deployment, verify HTTPS cookies, account isolation, denied anonymous
downloads, private bucket access, worker delivery, backups, and restore. Review
provider access logs and retention separately: application log redaction cannot
change a hosting provider's own request logging. Local tests do not certify a
live provider configuration.

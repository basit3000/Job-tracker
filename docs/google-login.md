# Public accounts and Google sign-in

Users can register at `/register` and sign in at `/login` using email/password.
Public registration defaults to enabled in local configuration and Compose.
`PUBLIC_SIGNUP_ENABLED=false` closes new registration, including Google signup,
while existing accounts can still sign in. Each account owns its own records,
uploads, exports, devices, and change feed.

## Google setup without a public URL

You can configure local development before choosing a hosting provider/domain.
Google permits loopback HTTP redirects for development web clients. See
[Google's server-side OAuth setup](https://developers.google.com/identity/protocols/oauth2/web-server)
for client creation and exact redirect matching.

1. Create/select a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Open **Google Auth platform**, configure the app's branding and audience, then
   open **Clients** and choose **Create client** with type **Web application**.
3. Add this exact authorized redirect URI:
   `http://localhost:5000/auth/google/callback`.
4. Save the client ID and client secret privately. Put them in the ignored `.env`
   using `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Set
   `GOOGLE_REDIRECT_URI=http://localhost:5000/auth/google/callback` and keep
   `PUBLIC_SIGNUP_ENABLED=true`.
5. Install the updated requirements, back up an existing database/uploads, run
   `flask --app run.py db upgrade`, and restart the app.
6. Open `http://localhost:5000/login` or `/register` and choose **Continue with
   Google**. Use the same hostname as the registered callback; mixing localhost
   and 127.0.0.1 loses the browser's OAuth session cookie.

Keep the development server bound to loopback, as `python run.py` and the
Compose port mapping do. The HTTP exception requires a loopback callback and
the matching request hostname; public deployment callbacks require HTTPS.

Use Google's permitted testing audience when evaluating an unpublished client;
if Google requires a test-user list for your project, add your test account there.
Do not commit a downloaded OAuth credentials file. The browser sends no client
secret; the server uses it only when exchanging the authorization code.

The Google button is hidden until both credentials are configured. Setting only
one fails startup with a configuration message. Email/password registration and
login continue to work when Google is unconfigured or unavailable.

## Existing accounts

Google signup creates an account only after a verified OpenID Connect sign-in.
It stores the Google subject ID and verified email, with no password credential.
The subject ID identifies subsequent sign-ins even if Google changes the email.
No profile name, photo, access token, refresh token, or ID token is retained.

An existing email/password account is not automatically merged by email. Sign in
with its password, open **Account settings**, confirm the current password, and
choose **Connect Google**. Select the Google account with the same email. This
explicit connection preserves the account's existing records and password login.
Google-only accounts continue signing in with Google; setting/resetting passwords
and unlinking providers are outside this change.

The implementation uses Google's verified stable `sub`, following
[Google's identity guidance](https://developers.google.com/identity/openid-connect/reference).
It does not infer account ownership from an email match or trust browser-supplied
Google profile fields.

## Deploying later

Register your chosen HTTPS callback, for example
`https://tracker.example.com/auth/google/callback`, in the Google web client's
authorized redirects and set that exact value in `GOOGLE_REDIRECT_URI`.
Use production credentials/audience settings as appropriate for your Google
project. Keep secrets in private deployment configuration. Use secure cookies,
stable `SECRET_KEY`, debug off, and the trusted proxy setup in
[deployment instructions](deployment.md). Public callbacks must use HTTPS.

Google flows start with a CSRF-protected POST. Authlib validates state, the PKCE
exchange, the ID token signature, issuer, audience, expiration, and nonce. The
app additionally checks verified email, nonce, flow age (ten minutes), and the
same signed-in account when linking. Login rotates the session. Cancellation,
provider outages, and verification failures use generic messages without tokens
or provider payloads.

The callback response uses `Referrer-Policy: no-referrer`. Default Werkzeug and
Gunicorn access logging filters remove its query string, and Authlib token debug
logging is disabled. Configure your reverse proxy/access monitoring to omit or
redact callback query strings too; this app cannot control upstream logs.
Do not log authorization headers, provider responses, or session cookies.

## Verification

`tests/test_google_auth.py` runs Authlib against fictional RSA-signed tokens with
only provider HTTP transport replaced. It tests signup/repeated login, explicit
linking, existing email collisions, closed registration, CSRF, safe redirects,
state/session boundaries, expiry, invalid signatures/claims, cancellation,
timeouts, logging redaction, factory isolation, and migration preservation.

Opt-in Chromium tests exercise public email/password signup and Google
signup/login/linking at desktop/mobile sizes. They simulate Google consent and
never access a real account. Run the test commands in the README. A final live
Google sign-in with your configured credentials, and HTTPS/proxy verification on
your chosen hosting platform, remain deployment checks.

# Web-layer security checklist

Operator-facing reference for the Korpus Django web layer (`web/`). Keep it
current whenever a security-relevant setting changes.

## Settings (what and why)

### `config/settings/base.py` (all environments)

| Setting | Value | Why |
| --- | --- | --- |
| `RATELIMIT_USE_CACHE` | `"default"` | Point django-ratelimit at the shared cache explicitly; counters must be shared across worker processes. |
| `SESSION_COOKIE_HTTPONLY` | `True` | JS cannot read the session cookie (blocks cookie theft via XSS). |
| `SESSION_COOKIE_SAMESITE` | `"Lax"` | Session cookie not sent on cross-site sub-requests; still allows top-level navigation. |
| `CSRF_COOKIE_SAMESITE` | `"Lax"` | Same protection for the CSRF cookie. |
| `SESSION_COOKIE_AGE` | `43200` (12h) | Bounds the window a stolen session cookie stays valid. |
| `SESSION_EXPIRE_AT_BROWSER_CLOSE` | `False` | Sessions keep the 12h lifetime across browser restarts (predictable expiry). |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | `52_428_800` (50 MB) | Rejects oversized request bodies before parsing; aligned with the batch upload cap. |
| `FILE_UPLOAD_MAX_MEMORY_SIZE` | `5 MB` | Files over 5 MB stream to a temp file instead of buffering in memory. |

### `config/settings/prod.py` (production only)

| Setting | Value | Why |
| --- | --- | --- |
| `DEBUG` | `False` | Never expose tracebacks/settings in production. |
| `SECRET_KEY` | env `KORPUS_SECRET_KEY`, fail loud | Required; also rejected if < 50 chars or < 5 distinct chars (weak-key guard). |
| `ALLOWED_HOSTS` | env `KORPUS_ALLOWED_HOSTS`, fail loud if empty | Blocks Host-header attacks; refuses to boot without an explicit allowlist. |
| `CSRF_TRUSTED_ORIGINS` | env `KORPUS_CSRF_TRUSTED_ORIGINS` | Origins trusted for cross-origin POSTs (also used by the lead endpoint's origin check). |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `True` | Cookies sent only over HTTPS. |
| `SECURE_HSTS_SECONDS` | `31536000` (1 year) | Browsers force HTTPS for a year. |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True` | HSTS applies to all subdomains. |
| `SECURE_HSTS_PRELOAD` | `True` | Eligible for the browser HSTS preload list. |
| `SECURE_CONTENT_TYPE_NOSNIFF` | `True` | Disables MIME sniffing. |
| `SECURE_REFERRER_POLICY` | `"same-origin"` | Referrer not leaked to third parties. |
| `X_FRAME_OPTIONS` | `"DENY"` | No framing — clickjacking defense. |
| `SECURE_PROXY_SSL_HEADER` | `("HTTP_X_FORWARDED_PROTO", "https")` | Django trusts Caddy's forwarded-proto header to know the edge is HTTPS. |
| `SECURE_SSL_REDIRECT` | `False` (intentional) | Caddy owns the HTTP->HTTPS redirect at the edge; redirecting again on the internal plain-HTTP hop risks a loop. |
| `SILENCED_SYSTEM_CHECKS` | `["security.W008"]` | Silences ONLY the SSL-redirect warning, deliberately, per the line above. Everything else must stay a zero-warning gate. |
| `LOGGING` | structured lines to stdout, `django`+apps at INFO, `django.security` at WARNING | Captured by the process manager; NEVER logs request bodies. |
| Admin URL | stays `/admin/` | Documented decision: obscuring the path is not a real control; the real defense is auth + rate limiting + HTTPS. |
| `DEBUG_PROPAGATE_EXCEPTIONS` | unset | Left at Django default (off) so exceptions don't propagate raw. |

## Secrets inventory

None of these may ever appear in shell `argv`, application logs, or git.
Pass them via environment variables (or a secrets file the process manager
injects), never on the command line.

| Secret | Used by | Notes |
| --- | --- | --- |
| `KORPUS_SECRET_KEY` | Django | Signing/session key. Rotating invalidates existing sessions. |
| `KORPUS_FERNET_KEY` | `connections.crypto` | Encrypts connector credentials at rest. See rotation caveat below. |
| `ANTHROPIC_API_KEY` | engine LLM provider | LLM access; billable. |
| DB password | `POSTGRES_PASSWORD` | Postgres auth. |
| SMTP creds | `KORPUS_EMAIL_HOST_USER` / `KORPUS_EMAIL_HOST_PASSWORD` | Outbound mail. |
| `KORPUS_CONSUMER_KEY` / `KORPUS_CONSUMER_SECRET` | WooCommerce CLI connector | Never pass on argv — env only. |

## Layered defenses

### Public lead endpoint (`leads.views.lead_create`)

The landing page is a static file served by Caddy, not rendered by Django,
so there is no Django CSRF token to embed — the view is deliberately
`@csrf_exempt`. That is compensated by a layered defense appropriate for a
public, session-less JSON endpoint:

1. Rate limit by IP (`5/h`) — caps abuse volume.
2. Origin/Referer host check against own host + `CSRF_TRUSTED_ORIGINS` — a
   lightweight same-origin check standing in for the CSRF token.
3. Honeypot field (`website`) — silently swallows simple bots.
4. Strict payload size / shape / field validation (10 KB body cap).

There is no cookie-based privilege for an attacker to ride here; worst case
of a forged request is a spurious `Lead` row.

### Login (`common.views.RateLimitedLoginView`)

- Two stacked POST-only rate limits: `10/min` per IP and `5/min` per
  (username+IP). Tripping either re-renders the login page with HTTP 429 and
  a generic non-field error — it never reveals whether the account exists.
- Backed by the shared cache (`RATELIMIT_USE_CACHE`), so limits hold across
  worker processes.

### Upload limits

- Request-body cap: 50 MB (`DATA_UPLOAD_MAX_MEMORY_SIZE`).
- Engine enforces a separate 64 MB cap on any single zip member (zip-bomb
  defense) during batch ingest.

### Org isolation (`common.org.OrgMembershipRequiredMixin`)

- Views under an `org_slug` resolve the org, then require `is_staff` or an
  `accounts.Membership`. Non-members get **404, not 403**, so the existence
  of an org slug is never leaked. Combine with `LoginRequiredMixin` first in
  the MRO so anonymous users are redirected to login.

### Credential encryption at rest (`connections.crypto`)

- Connector credentials are Fernet-encrypted (AES-128-CBC + HMAC-SHA256)
  before storage, keyed by `KORPUS_FERNET_KEY` held outside the DB, so a DB
  dump alone never exposes store credentials.
- **Rotation caveat:** rotating `KORPUS_FERNET_KEY` makes every existing
  ciphertext undecryptable (surfaced as `CredentialDecryptionError`).
  Re-enter connector credentials after any key rotation.

## Re-verify at each deploy

- [ ] `manage.py check --deploy --settings=config.settings.prod` → ZERO
      issues (1 silenced: `security.W008`, expected).
- [ ] `manage.py check` (dev) → clean.
- [ ] Cache table exists: `manage.py createcachetable` has run in the target
      environment (rate limiting depends on it).
- [ ] All required secrets set in the environment; none present in argv,
      logs, or git.
- [ ] Database backups exist AND a restore has been test-run.
- [ ] TLS terminates at Caddy; app reachable only via the proxy.

## Manual verification notes

`config` and `common` are not installed apps, so they carry no automated
tests here. The login rate limit was verified manually via the Django test
client (locmem cache override): 11+ rapid POSTs to `/app/login/` return 200
until the per-(username+IP) `5/m` bucket trips, after which every response is
429 with the login page re-rendered (generic error, no account disclosure).
Re-run that check after any change to `common/views.py` or the ratelimit
settings.

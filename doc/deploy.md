# Deploying Korpus

Operator-facing guide for standing up a production Korpus instance. Assumes
you already have `deploy/Dockerfile`, `deploy/docker-compose.yml`,
`deploy/Caddyfile`, `.env.example`, and `deploy/backup.sh` from this repo.

## Prerequisites

- An Ubuntu VPS (22.04 LTS or newer) with a public IPv4 address.
  - Prefer an **EU-region** provider/region for data residency (e.g.
    Hetzner `nbg1`/`fsn1`/`hel1`, or a DigitalOcean EU datacenter such as
    `ams3`/`fra1`) — Korpus processes Serbian retailers' catalog and
    customer-adjacent lead data.
- Docker Engine + the `docker compose` plugin installed
  (`docker compose version` should work).
- A DNS **A record** for your domain (e.g. `korpus.rs`) pointing at the
  VPS's IP, plus a `www` A/CNAME if you'll use it — Caddy needs this to
  resolve before it can issue a TLS certificate.
- Ports 80 and 443 open inbound (Caddy needs 80 for the ACME HTTP-01
  challenge as well as 443).

## 1. Clone the repo

```bash
git clone <repo-url> /opt/korpus
cd /opt/korpus
```

## 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in every `changeme-*` placeholder. In particular:

- **`KORPUS_SECRET_KEY`** — generate with:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
- **`KORPUS_FERNET_KEY`** — generate with:
  ```bash
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  (needs the `cryptography` package; if you don't have it locally, run
  this one-liner inside the app container after first boot instead —
  see the troubleshooting note at the end of this doc.)
- `KORPUS_DOMAIN` / `KORPUS_ACME_EMAIL` — your real domain and an email
  Let's Encrypt can reach about certificate problems.
- `KORPUS_ALLOWED_HOSTS` / `KORPUS_CSRF_TRUSTED_ORIGINS` — must match
  `KORPUS_DOMAIN` (and `www.` variant if used).
- `POSTGRES_PASSWORD` — a strong random password.
- `ANTHROPIC_API_KEY` — from the Anthropic Console.
- `KORPUS_EMAIL_*` — your SMTP provider's credentials (used for password
  resets and lead notifications).

`.env` is git-ignored — never commit it.

## 3. Build and start the stack

`deploy/docker-compose.yml` doesn't set an explicit Compose project name,
so a plain `docker compose -f deploy/docker-compose.yml ...` (no `-p`)
would default to naming the project after the `deploy/` directory (e.g.
its `media` volume would become `deploy_media`). Every command below
instead passes `-p korpus` explicitly to pin the project name —
`deploy/backup.sh` assumes this same `korpus` name when it locates the
media volume to back up, so keep using `-p korpus` on every manual
invocation too.

```bash
docker compose -p korpus -f deploy/docker-compose.yml up -d --build
```

This starts `db` (Postgres), `app` (gunicorn on :8000, behind Caddy),
`worker` (django-q background tasks — batch generation), and `caddy`
(reverse proxy + auto-HTTPS, serving `../landing` as the static marketing
site at `/`).

Watch the first boot:

```bash
docker compose -p korpus -f deploy/docker-compose.yml logs -f caddy app
```

Caddy should log a successful certificate issuance for `KORPUS_DOMAIN`
within a minute or two of DNS resolving correctly.

## 4. Migrations and cache table

`deploy/entrypoint.sh` already runs `migrate` and `createcachetable`
automatically every time the `app` (and `worker`) container starts, so
nothing to do here on a normal boot. If you ever need to re-run either by
hand (e.g. after a manual `docker compose ... exec` into a stopped state):

```bash
docker compose -p korpus -f deploy/docker-compose.yml exec app python web/manage.py migrate
docker compose -p korpus -f deploy/docker-compose.yml exec app python web/manage.py createcachetable
```

(`createcachetable` is required — django-ratelimit and the shared cache
backend depend on it; see `doc/security-checklist.md`.)

## 5. Create a superuser

```bash
docker compose -p korpus -f deploy/docker-compose.yml exec app python web/manage.py createsuperuser
```

## 6. Create the first organization and user

Log into the Django admin at `https://<KORPUS_DOMAIN>/admin/` with the
superuser account, then:

1. Create an `accounts.Org` (organization) row.
2. Create the org's first real user (or use the superuser) and add a
   `Membership` linking them to that org.
3. Have the user log in at `https://<KORPUS_DOMAIN>/app/login/` and
   confirm they land on their org's dashboard.

## 7. Smoke checklist

Run through this after every fresh deploy and every update:

- [ ] Landing page loads at `https://<KORPUS_DOMAIN>/` (static, served by
      Caddy, not Django).
- [ ] `https://<KORPUS_DOMAIN>/app/login/` renders the login form and
      accepts the account created in step 6.
- [ ] Upload a small test CSV as a batch using provider **`fake`** (no
      Anthropic spend, deterministic output) and confirm it completes.
- [ ] Open the batch's review queue, confirm generated rows render, and
      approve at least one item.
- [ ] Confirm `/admin/` is reachable and requires login.
- [ ] Confirm a request to `/media/...` (anything under the media root)
      is **not** publicly reachable — only authenticated in-app download
      links should work.
- [ ] Submit the landing page's contact form once and confirm
      `LEAD_NOTIFY_EMAIL` receives the notification.

## 8. Install the backup cron

```bash
sudo cp deploy/backup.sh /opt/korpus/deploy/backup.sh   # if not already there
sudo chmod +x /opt/korpus/deploy/backup.sh
sudo crontab -e
```

Add:

```
0 3 * * * /opt/korpus/deploy/backup.sh >> /var/log/korpus-backup.log 2>&1
```

This dumps Postgres and tars the media volume nightly to
`/var/backups/korpus/`, keeping 14 days locally. Copy that directory
offsite periodically (e.g. `rsync`/`rclone` to object storage in the same
EU region) — a local-disk-only backup doesn't protect against VPS loss.
**Periodically test a restore** — an untested backup is not a backup (see
`doc/security-checklist.md`).

## 9. Update procedure

```bash
cd /opt/korpus
git pull
docker compose -p korpus -f deploy/docker-compose.yml build
docker compose -p korpus -f deploy/docker-compose.yml up -d
docker compose -p korpus -f deploy/docker-compose.yml exec app python web/manage.py migrate
```

Re-run the smoke checklist (step 7) after every update.

## Logs

All services log to stdout/stderr, captured by Docker:

```bash
docker compose -p korpus -f deploy/docker-compose.yml logs -f app      # gunicorn / Django
docker compose -p korpus -f deploy/docker-compose.yml logs -f worker   # django-q background tasks
docker compose -p korpus -f deploy/docker-compose.yml logs -f caddy    # reverse proxy / TLS
docker compose -p korpus -f deploy/docker-compose.yml logs -f db       # Postgres
```

Django's structured log format (`config/settings/prod.py`) never logs
request bodies — uploaded catalogs and connector credentials do not appear
in these logs by design.

## Notes

- **Data residency:** run the VPS in an EU region (Hetzner or DigitalOcean
  EU datacenters both work well) so catalog and lead data stays in the EU.
- **`/media/*` is intentionally never proxied or served by Caddy** — see
  the comment block in `deploy/Caddyfile`. All file downloads go through
  authenticated Django views. Do not add a `/media/*` route to the
  Caddyfile.
- **TLS/HSTS:** Caddy handles auto-HTTPS entirely; Django additionally
  sends its own security headers (including HSTS) on every response it
  renders. See the comment at the top of `deploy/Caddyfile` for how the
  two layers divide responsibility without duplicating headers.
- **WooCommerce CLI connector** (`KORPUS_CONSUMER_KEY`/`_SECRET` in
  `.env.example`) is for the standalone `pipeline` publish CLI, not the
  web app — leave those commented out unless you're running that CLI
  directly against a store from this machine.

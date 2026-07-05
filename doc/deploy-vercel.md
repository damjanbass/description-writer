# Deploying Korpus (web/) to Vercel

The VPS + Docker + Caddy stack (doc/deploy.md) remains the reference
deployment. This runbook covers the alternative serverless deployment on
Vercel, using `config.settings.vercel`:

| Concern | VPS/compose | Vercel |
|---|---|---|
| Settings module | `config.settings.prod` | `config.settings.vercel` |
| Postgres | compose `db` container (`POSTGRES_*`) | Neon via Vercel Marketplace (`DATABASE_URL`) |
| Uploaded catalogs | `KORPUS_MEDIA_ROOT` volume (FileSystemStorage) | Postgres rows (`batches.dbstorage.DatabaseStorage`) |
| Background work | django-q `worker` container | Upstash QStash → `POST /api/tasks/run`, chunked (240 s/chunk) |
| descriptions.csv / review_queue.json | generated from the DB on download | same (single code path) |
| TLS termination | Caddy | Vercel edge |

Platform constraints to know:

- **Hobby plan functions run at most 300 s** (Fluid compute; it is both the
  default and the maximum, so no `vercel.json` is needed). Tasks self-budget
  at 240 s per chunk and re-dispatch their own continuation via QStash.
- **Request bodies are capped at ~4.5 MB by the platform**, so uploaded
  catalogs are effectively ≤4.5 MB here regardless of the app's own 50 MB
  form cap. Split larger catalogs, or use the VPS deployment.
- **Hobby cron runs at most once per day** — useless for task scheduling,
  which is why QStash (HTTP callback queue, free tier 1,000 msgs/day) drives
  the chunk chain instead. A ~500-product batch uses ~20 messages.
- No shell on Vercel: migrations and superuser creation run **from your
  machine against the Neon database** (step 4).

## 1. Provision Postgres (Neon)

Vercel dashboard → the `description-writer` project → **Storage** →
**Create Database** → Marketplace → **Neon** (free tier). Accept the
defaults so the integration injects `DATABASE_URL` (pooled) and
`DATABASE_URL_UNPOOLED` (direct) into the project's env vars.

## 2. Create the QStash queue

[console.upstash.com](https://console.upstash.com) → QStash → copy the
**QSTASH_TOKEN** from the request builder panel. Free tier (1,000
messages/day) is plenty for pilot volume.

## 3. Set project env vars (Production environment)

Vercel dashboard → project → Settings → Environment Variables:

| Var | Value |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.vercel` |
| `KORPUS_SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `KORPUS_FERNET_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `KORPUS_ALLOWED_HOSTS` | `description-writer.vercel.app` |
| `KORPUS_CSRF_TRUSTED_ORIGINS` | `https://description-writer.vercel.app` |
| `KORPUS_TASK_TOKEN` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `KORPUS_TASK_CALLBACK_BASE` | `https://description-writer.vercel.app` |
| `QSTASH_TOKEN` | from step 2 |
| `ANTHROPIC_API_KEY` | optional until real (non-fake) generation is wanted |

(`DATABASE_URL` is already there from step 1. Add a custom domain to
`KORPUS_ALLOWED_HOSTS`/`KORPUS_CSRF_TRUSTED_ORIGINS`/`KORPUS_TASK_CALLBACK_BASE`
when one is attached.)

## 4. Initialize the database (from your machine)

Use the **unpooled** URL (direct connection — right for DDL) from the Vercel
env var listing, plus the same secrets, for a few one-off local commands.
PowerShell:

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.vercel"
$env:DATABASE_URL       = "<value of DATABASE_URL_UNPOOLED>"
$env:KORPUS_SECRET_KEY  = "<value from step 3>"
$env:KORPUS_ALLOWED_HOSTS = "description-writer.vercel.app"
$env:KORPUS_FERNET_KEY  = "<value from step 3>"

cd web
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py createcachetable
..\.venv\Scripts\python.exe manage.py createsuperuser
# Optional demo org + seeded demo batch (fake provider, no LLM calls):
# create the org + membership in /admin first, then:
# ..\.venv\Scripts\python.exe manage.py seed_demo <org-slug>
```

Unset those env vars (or close the shell) afterwards.

## 5. Deploy and smoke-test

```powershell
vercel deploy --prod
```

Then, on https://description-writer.vercel.app:

1. `/app/login/` — log in as the superuser; `/admin/` loads with styling
   (static via WhiteNoise).
2. Create an org + membership in `/admin/` if not done in step 4.
3. Upload `web/static/samples/korpus-primer.csv` (provider: fake) — the
   detail page shows live progress („obrađeno X od Y proizvoda") without
   full-page reloads; the batch finishes COMPLETED.
   This exercises the whole chain: upload → QStash publish → callback on
   `/api/tasks/run` → chunked generation → status endpoint.
4. Open an item, approve it; download `descriptions.csv` and
   `review_queue.json`.
5. „Učitaj demo seriju" button works (runs inline, no QStash involved).
6. With `ANTHROPIC_API_KEY` set: upload a *small* CSV with provider
   anthropic and confirm a real generation completes.

## Troubleshooting

- **Batch stuck UPLOADED/RUNNING**: any visit to its detail page re-kicks a
  stalled run (the status endpoint is the backstop — RUNNING with no
  progress heartbeat for 2 min, or UPLOADED for 1 min, re-dispatches).
  Check the QStash console's message log and Vercel function logs
  (`vercel logs <url>`).
- **401 in the QStash log**: `KORPUS_TASK_TOKEN` differs between the
  Vercel env and what the dispatching deployment sent — redeploy after
  changing env vars (they are baked in at deploy time).
- **500 on every page**: read the function log; the usual cause is a
  missing required env var (`KORPUS_SECRET_KEY`, `KORPUS_ALLOWED_HOSTS`,
  `DATABASE_URL`), which `config.settings.prod` fails loudly about at
  import.
- **Migrations out of date after a code change**: re-run step 4's
  `migrate` against the unpooled URL, then redeploy.

# Launch Checklist — Go-Live for Korpus

One-time pre-go-live verification. Complete in order.

## 1. DNS and networking

- [ ] **DNS A record**: `KORPUS_DOMAIN` (e.g., `korpus.rs`) resolves to the VPS public IP.
- [ ] **CNAME or secondary A record**: `www.KORPUS_DOMAIN` also resolves (required by Caddy cert issuance if `KORPUS_ALLOWED_HOSTS` includes it).
- [ ] **Ports**: 80 and 443 are open inbound on the VPS (Caddy needs 80 for ACME HTTP-01 challenge; both for TLS traffic).
- [ ] **Ping test**: `ping <VPS_IP>` responds; SSH into VPS succeeds.

## 2. Environment file (`.env`)

Copy `.env.example` to `.env` and populate **every** placeholder:

- [ ] **`KORPUS_SECRET_KEY`** — Generate with:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
  Must be ≥50 characters and ≥5 distinct characters.

- [ ] **`KORPUS_FERNET_KEY`** — Generate with:
  ```bash
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  (If `cryptography` is not installed locally, generate this inside the container after first boot.)

- [ ] **`KORPUS_DOMAIN`** — Exact domain the site is served on (e.g., `korpus.rs`; also the name Caddy requests a TLS cert for).

- [ ] **`KORPUS_ACME_EMAIL`** — Email Let's Encrypt uses for certificate expiry/problem notices (e.g., `damjan9494@gmail.com`).

- [ ] **`KORPUS_ALLOWED_HOSTS`** — Comma-separated: must include `KORPUS_DOMAIN` and any subdomains (e.g., `korpus.rs,www.korpus.rs`).

- [ ] **`KORPUS_CSRF_TRUSTED_ORIGINS`** — Comma-separated with scheme (e.g., `https://korpus.rs,https://www.korpus.rs`). Must match `KORPUS_ALLOWED_HOSTS`.

- [ ] **`POSTGRES_PASSWORD`** — Strong random password (e.g., 16+ chars, mixed case, symbols).

- [ ] **`ANTHROPIC_API_KEY`** — From Anthropic Console; required for production LLM calls.

- [ ] **`KORPUS_EMAIL_HOST`, `KORPUS_EMAIL_PORT`, `KORPUS_EMAIL_HOST_USER`, `KORPUS_EMAIL_HOST_PASSWORD`** — SMTP provider credentials (password resets, lead notifications). Test with a dummy SMTP service first if needed (e.g., Mailtrap for staging).

- [ ] **`LEAD_NOTIFY_EMAIL`** — Where contact-form leads are sent (e.g., `damjan9494@gmail.com`).

- [ ] **`KORPUS_MEDIA_ROOT`** — Path under which uploaded catalogs and outputs are stored (e.g., `/data/media`; must be on a persistent volume in Docker).

- [ ] **Other Postgres vars** (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_HOST`, `POSTGRES_PORT`) — Match your docker-compose setup; defaults usually fine.

- [ ] **`DJANGO_SETTINGS_MODULE`** — Set to `config.settings.prod` (required).

- [ ] **`.env` is git-ignored** — Verify with `git status .env` (should not appear).

## 3. Build and start the stack

```bash
cd /opt/korpus
docker compose -p korpus -f deploy/docker-compose.yml up -d --build
```

- [ ] **No build errors**: Images build successfully (check `docker compose -p korpus logs -f`).
- [ ] **All services start**: `docker compose -p korpus ps` shows `app`, `worker`, `db`, `caddy` all running (Status=Up).
- [ ] **Caddy issues TLS cert**: Watch logs:
  ```bash
  docker compose -p korpus -f deploy/docker-compose.yml logs -f caddy
  ```
  Should show successful cert issuance for `KORPUS_DOMAIN` within 1–2 minutes. If it hangs, check that DNS is resolving and ports 80/443 are open.
- [ ] **App is healthy**: `docker compose -p korpus logs -f app | tail -20` shows no startup errors.

## 4. Database migrations and cache

Migrations and cache table creation run automatically in `deploy/entrypoint.sh`, so nothing to do here on a normal boot. Verify they succeeded:

```bash
docker compose -p korpus -f deploy/docker-compose.yml exec app python web/manage.py migrate --check
docker compose -p korpus -f deploy/docker-compose.yml exec app python web/manage.py check
```

- [ ] **No migration issues**: Both commands return clean (no pending migrations).

## 5. Superuser creation

```bash
docker compose -p korpus -f deploy/docker-compose.yml exec app python web/manage.py createsuperuser
```

- [ ] **Superuser created**: Prompted for username, email, password. Save these credentials securely.
- [ ] **Admin access**: Log into `https://<KORPUS_DOMAIN>/admin/` with the superuser account. Should see Django admin dashboard.

## 6. First organization and pilot user

Log into `/admin/` as the superuser and:

1. **Create an Org**:
   - Go to Accounts > Organizations.
   - Click "Add Organization".
   - Name: (your first pilot company name; e.g., "Pilot Retailer").
   - Slug: (lowercase, no spaces; e.g., "pilot-retailer").
   - Save.

2. **Create or assign a User**:
   - Go to Auth > Users.
   - Create a new user (or use the superuser).
   - Email: (pilot contact email).
   - First/Last name: (optional).
   - Save.

3. **Create a Membership**:
   - Go to Accounts > Memberships.
   - Click "Add Membership".
   - User: (select the user above).
   - Organization: (select the Org above).
   - Role: (e.g., "manager" or similar; role choices depend on `accounts/models.py`).
   - Save.

- [ ] **Membership created**: Link established between user and org.
- [ ] **User can log in at `/app/login/`**: Test with the user's credentials. Should land on `/app/<org_slug>/batches/`.

## 7. Backup infrastructure

### 7a. Install backup script

```bash
sudo cp deploy/backup.sh /opt/korpus/deploy/backup.sh
sudo chmod +x /opt/korpus/deploy/backup.sh
```

- [ ] **Script is executable**: `ls -la /opt/korpus/deploy/backup.sh` shows `-rwxr-xr-x`.

### 7b. Install cron job

```bash
sudo crontab -e
```

Add:
```
0 3 * * * /opt/korpus/deploy/backup.sh >> /var/log/korpus-backup.log 2>&1
```

- [ ] **Cron job installed**: `sudo crontab -l` includes the line above.

### 7c. Manual backup test

Run the script once to verify it works:

```bash
/opt/korpus/deploy/backup.sh
```

- [ ] **No errors**: Script completes without failure (exit code 0).
- [ ] **Backup files created**: Check `/var/backups/korpus/`:
  ```bash
  ls -lh /var/backups/korpus/
  ```
  Should show `korpus-YYYY-MM-DD.sql` and `korpus-media-YYYY-MM-DD.tar.gz`.

### 7d. Restore-from-backup drill (real restore test, not just backup creation)

This is **mandatory** — an untested backup is not a backup. Follow `doc/runbook.md` "Restore-from-backup drill":

1. Stop the app and worker (do NOT do this in production without a maintenance window):
   ```bash
   docker compose -p korpus stop app worker
   ```

2. Restore the Postgres dump:
   ```bash
   docker compose -p korpus exec -T db psql -U korpus -d korpus -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   docker compose -p korpus exec -T db psql -U korpus -d korpus < /var/backups/korpus/korpus-YYYY-MM-DD.sql
   ```

3. Restore the media volume:
   ```bash
   docker run --rm -v korpus_media:/data/media -v /var/backups/korpus:/backup alpine \
     sh -c "rm -rf /data/media/* && tar xzf /backup/korpus-media-YYYY-MM-DD.tar.gz -C /data/media"
   ```

4. Restart everything:
   ```bash
   docker compose -p korpus up -d
   ```

5. Verify the restore:
   - `docker compose -p korpus logs app --tail=50` — no startup errors.
   - Log into `/admin/` — see at least the superuser and pilot org/user created above.
   - `docker compose -p korpus exec -T db psql -U korpus -d korpus -c "SELECT count(*) FROM accounts_organization;"`
     Should return the orgs you created.

- [ ] **Restore completed successfully**: Database and media restored; all data present.
- [ ] **Drill documented and passed**: Restore is confirmed to work (not just assumed).

## 8. Health checks

### 8a. Security validation

```bash
docker compose -p korpus -f deploy/docker-compose.yml exec app \
  python web/manage.py check --deploy --settings=config.settings.prod
```

- [ ] **Zero issues** (or 1 silenced: `security.W008` — that's expected; all others must be zero).

### 8b. Dev check (no deploy flag)

```bash
docker compose -p korpus -f deploy/docker-compose.yml exec app \
  python web/manage.py check
```

- [ ] **Clean**: No warnings or errors.

### 8c. Static files

Caddy serves the landing page (`landing/` directory) as static content at `/`. Verify:

```bash
curl -I https://<KORPUS_DOMAIN>/ 2>/dev/null | grep -E '^(HTTP|Server)'
```

- [ ] **HTTP 200 OK**: Landing page loads.
- [ ] **Headers correct**: HSTS, Content-Type, etc. present (check with `curl -I`).

## 9. Run the smoke test

Execute `doc/smoke.md` end-to-end in a non-production environment first (staging), then in production with a test org and batch.

- [ ] **All smoke test steps pass**: See `doc/smoke.md` for the full checklist.
  - Landing page loads offline and online.
  - Лат/Ћир toggle works, brands protected.
  - Lead form submits, notification sent, row in admin.
  - Batch upload, review, approve/reject, publish all work.
  - CLI unchanged (generate → review → publish).
  - Rate limits enforced.
  - Transliteration 0% error on brand names.

## 10. Landing page OG metadata

The landing page has Open Graph tags for link previews. Verify with a link-preview checker:

1. Use a service like [Open Graph Debugger](https://www.opengraph.xyz/) or similar.
2. Paste `https://<KORPUS_DOMAIN>/` and check the preview.
3. **Expected**:
   - og:title: "Korpus — ispravni opisi proizvoda na srpskom"
   - og:description: "Mašina za gramatičku tačnost i usklađenost. Oba pisma, iz jedne generacije. Bez izmišljanja."
   - og:image: Points to `https://<KORPUS_DOMAIN>/og.png` (or relative path resolved correctly).
   - og:url: Matches `KORPUS_DOMAIN`.

- [ ] **OG tags present and correct**: Preview renders title, description, and image.
- [ ] **Image (`og.png`) exists** in `landing/og.png` and is accessible over HTTPS.

## 11. Venture kill criterion (from `doc/masterplan.md` section 5)

**This is the one item you cannot skip or fudge.**

> **3 paid pilots from named Serbian retailers before Phase 2 connector engineering.**

- [ ] **At least 3 signed pilots** with:
  - Named retail companies (not generic "test" accounts).
  - €2.5k+ commitment (or equivalent local currency).
  - Explicit permission to use as reference (ask explicitly).
  - Signed SOW or MSA if your legal prefers.

If you do NOT have 3 paid pilots at this point, do **NOT** proceed with Phase 2 (Selltico/TAU integration). The wedge is only proven real if the market votes with money.

- [ ] **Pilot 1**: (company name, signed, amount, date).
- [ ] **Pilot 2**: (company name, signed, amount, date).
- [ ] **Pilot 3**: (company name, signed, amount, date).

## 12. Final sign-off

- [ ] **Checklist complete**: Every item above has been checked and verified.
- [ ] **All services healthy**: `docker compose -p korpus ps` shows all containers running.
- [ ] **Admin accessible**: Can log in, create orgs/users/memberships.
- [ ] **Smoke test passed**: All steps in `doc/smoke.md` succeed.
- [ ] **Backups tested**: Restore drill completed and verified.
- [ ] **Kill criterion met**: 3 paid pilots signed and documented.
- [ ] **Go-live approved**: Team consensus that the instance is ready for production traffic.

**Date go-live approved**: _______________

**Approved by**: _______________

---

## Rollback procedure (if needed)

If a critical issue is discovered after launch, you have a backup. See `doc/runbook.md` "Restore-from-backup drill" and follow the steps in reverse: stop services, restore from the most recent pre-launch backup, restart.

A rollback is safe because Postgres and media dumps are immutable; the database and files can be restored cleanly to the exact state before go-live.

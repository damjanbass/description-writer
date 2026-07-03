# Operations runbook

Operator-facing procedures for running Korpus in production. Pairs with
`doc/security-checklist.md` (settings/secrets reference) — this document is
about what to *do*, not what's configured.

Assumes the standard deploy: `docker compose` stack with `app` (gunicorn),
`worker` (django-q qcluster), `db` (Postgres), `caddy` (TLS-terminating
reverse proxy), and a mounted media volume at `/data/media`.

## Restore-from-backup drill

Run this drill periodically (not just when disaster strikes) — an untested
backup is not a backup.

1. **Stop the app and worker** so nothing writes to the database or media
   volume during restore:

   ```
   docker compose stop app worker
   ```

2. **Restore the Postgres dump into a fresh db container.** Bring up a clean
   `db` service (or a scratch one) and pipe the dump in:

   ```
   docker compose exec -T db psql -U korpus -d korpus -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   docker compose exec -T db psql -U korpus -d korpus < backups/korpus-YYYY-MM-DD.sql
   ```

   (If the dump was made with `pg_dump -Fc` custom format, use `pg_restore`
   via `docker compose exec -T db pg_restore -U korpus -d korpus --clean --if-exists` instead, piping the `.dump` file in the same way.)

3. **Restore the media tar into the volume.** Extract directly into the
   mounted media path (adjust the volume name/path to match your compose
   file):

   ```
   docker run --rm -v korpus_media:/data/media -v "$(pwd)/backups":/backup alpine \
     sh -c "rm -rf /data/media/* && tar xzf /backup/korpus-media-YYYY-MM-DD.tar.gz -C /data/media"
   ```

4. **Start everything back up:**

   ```
   docker compose up -d
   ```

5. **Verify:**
   - `docker compose logs app --tail=50` — no startup errors.
   - Log into `/admin/` with a known account; confirm org/lead/batch data
     from before the backup is present.
   - Open a previously uploaded batch and confirm its output file downloads
     (proves the media volume restore worked, not just the DB).
   - `docker compose exec -T db psql -U korpus -d korpus -c "SELECT count(*) FROM batches_batch;"`
     sanity-checks row counts look right for the backup's vintage.

## Fernet key rotation

`KORPUS_FERNET_KEY` encrypts connector credentials (e.g. WooCommerce
consumer key/secret) at rest. **Current limitation: there is no in-place
re-encryption.** Rotating the key makes every previously stored ciphertext
undecryptable — the app surfaces this as `CredentialDecryptionError` the
next time it tries to use a stored credential.

Procedure:

1. Generate the new key:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. Set `KORPUS_FERNET_KEY` to the new value in the environment and restart
   `app` and `worker`.
3. **Re-enter every connector's credentials in `/admin/`.** Existing
   encrypted values are now unreadable and must be overwritten with fresh
   ciphertext under the new key; there's no way to recover the old
   plaintext from the DB.
4. Confirm each connector works again (e.g. trigger a small test batch) after
   re-entry.

Future work: a `MultiFernet`-based management command that decrypts under
the old key and re-encrypts under the new one in place, so rotation doesn't
require manual credential re-entry. Not implemented yet — until it exists,
budget time for step 3 whenever rotating this key.

## Log access

- `docker compose logs app` — Django/gunicorn request handling, structured
  lines (`level=... logger=...`).
- `docker compose logs worker` — django-q task execution (batch processing).
- `docker compose logs caddy` — edge TLS termination, access logs, upstream
  errors.
- Add `-f` to any of the above to follow, `--tail=N` to limit backlog.

`django.security` warnings are the ones to watch closely — they're floored
at WARNING regardless of the app logger's level, so they never get lost
below routine INFO noise. They look like:

```
2026-07-02 10:14:03 level=WARNING logger=django.security.SuspiciousOperation Invalid HTTP_HOST header: 'evil.example'.
```

A burst of these (bad Host headers, CSRF failures, disallowed origins) is
worth investigating — it usually means either a misconfigured
`KORPUS_ALLOWED_HOSTS`/`KORPUS_CSRF_TRUSTED_ORIGINS`, or someone probing the
public endpoint.

## Routine ops

**Creating an org + inviting a user** (admin steps, via `/admin/`):
1. Log in to `/admin/` as staff.
2. Under Accounts, create an `Org` (name, slug).
3. Create or select the `User` to invite.
4. Create a `Membership` linking the user to the org (set role as needed).
5. Have the user log in at `/app/login/` — they'll land in the org via its
   slug-scoped URLs.

**Re-running a failed batch:** batches are immutable runs — there is no
"retry" action. Fix whatever caused the failure (bad file, connector
credentials, transient error) and upload the source file again to start a
new batch. The failed batch stays in history for reference.

**Disk watch:** media artifacts (uploaded catalogs, generated outputs) only
grow — nothing currently prunes them. Monitor the media volume's free space
(`df -h` on the host, or `docker system df -v`) and plan for archival/cleanup
once volume size becomes a concern; no automated retention policy exists
yet.

**Postgres vacuum:** autovacuum is on by default and should be sufficient at
current scale. If query performance degrades or table bloat is suspected,
check `docker compose exec -T db psql -U korpus -d korpus -c "SELECT relname, n_dead_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;"`
before manually running `VACUUM ANALYZE`.

## Incident quick reference

**Leaked `SECRET_KEY`:**
1. Generate a new one: `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
2. Set `KORPUS_SECRET_KEY` to the new value in the environment.
3. Restart `app` and `worker`.
4. All existing sessions are invalidated immediately (users must log back
   in) — this is expected and is the point.

**Leaked `KORPUS_FERNET_KEY`:**
1. Follow the Fernet key rotation procedure above (generate, set, restart).
2. Re-enter all connector credentials in `/admin/` — treat the old
   ciphertext as compromised, not just unreadable.

**Stuck `qcluster` (worker not processing batches):**
1. Check `docker compose logs worker --tail=100` for the failure.
2. Restart just the worker: `docker compose restart worker`.
3. If batches are stuck mid-run, re-upload (batches are immutable — see
   "Re-running a failed batch" above) rather than trying to resume.

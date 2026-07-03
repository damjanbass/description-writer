# Smoke Test — Manual Pre-Release Checklist

Run this checklist end-to-end before every release. Each step has a specific expected result.

## 1. Landing page (offline)

1. Open `landing/index.html` in a browser with DevTools network set to **offline**.
2. **Expected**: Page renders completely without network calls:
   - Fonts load (check DevTools under offline mode — should fail gracefully per CSS).
   - Both demo cards render (hero section shows Nike example + dual-script panel).
   - All static content (hero, sections, pricing) visible and readable.
3. Click the **Лат / Ћир** toggle in the header.
4. **Expected**: Page text switches between latinica and ćirilica, BUT:
   - Fixed terms stay in latinica: Korpus, WooCommerce, iPhone, CSV, XLSX, SKU, Selltico, TAU, Nike, Crna kožna patika Nike, etc. (anything in `data-fixed` attributes).
   - User-facing copy (headings, body text) converts correctly between scripts.

## 2. Landing page lead form

1. Go to `https://<KORPUS_DOMAIN>/` (online; DNS resolving).
2. Scroll to "Spremni da očistite katalog?" section.
3. **Expected**: Lead form loads (fields: ime, email, firma, poruka).
4. Fill in the form with test data (e.g., ime=Test, email=test@example.com, firma=Test Co., poruka=Test message).
5. Submit the form.
6. **Expected**:
   - Form shows success message ("Hvala! Javićemo se u roku od 24h.").
   - POST to `/api/lead` succeeds (check DevTools network tab).
   - A new `Lead` row appears in `/admin/leads/lead/`.
   - An email arrives at `LEAD_NOTIFY_EMAIL` (check inbox for the send).

## 3. Web app — org + user + batch workflow

### 3a. Admin setup (org, user, membership)

1. Log into `/admin/` as superuser.
2. Create an `Organization` (Accounts > Organizations):
   - Name: "Test Org"
   - Slug: "test-org"
   - Save.
3. Create or select a `User` (Auth > Users).
4. Create a `Membership` (Accounts > Memberships):
   - User: (select or create one).
   - Organization: "Test Org".
   - Role: (any; suggest "manager").
   - Save.
5. **Expected**: Membership row appears with org/user linked.

### 3b. Login and batch upload

1. Log out of `/admin/`.
2. Go to `/app/login/`.
3. Log in with the user created above.
4. **Expected**: Redirected to `/app/test-org/batches/` (org dashboard).
5. Click "Učitaj novu seriju" (new batch).
6. Fill in the form:
   - Naziv: "Test Batch"
   - Katalog (CSV/XLSX): Upload a small test file with 3–5 products (columns: id, brand, color, material, size).
   - Izvorno pismo: Latinica.
   - Provajder: **"Test (bez LLM)"** (the Fake provider).
   - Model: Leave blank.
   - Submit.
7. **Expected**:
   - Batch shows status "running" then "completed".
   - Batch list shows "Test Batch" with item count and status "Completed".

### 3c. Review queue (approve/reject)

1. Click into the "Test Batch" to open its detail page.
2. **Expected**: Review queue panel loads with dual-script display:
   - Items listed with product IDs.
   - Each item shows ćirilica and latinica panels side-by-side.
   - Provenance highlights (claims linked to source attributes) visible on hover/click.
3. Click **approve** on the first item.
4. **Expected**: Item status changes to "Approved"; AuditLog row created (check `/admin/batches/auditlog/`).
5. Click **reject** on the second item with a reason.
6. **Expected**: Item status changes to "Rejected"; reason stored; AuditLog row created.
7. Leave remaining items pending.

### 3d. Publish to WooCommerce sandbox

1. In `/admin/`, create a `ConnectorCredential`:
   - Organization: "Test Org"
   - Connector: "WooCommerce"
   - Label: "Test WooCommerce Sandbox"
   - Base URL: (your WooCommerce sandbox URL or test store).
   - Consumer Key / Consumer Secret: (test credentials from your sandbox).
   - Save.
2. Return to the batch detail page.
3. Click "Objavi" (publish).
4. **Expected**: Form shows credential dropdown; select "Test WooCommerce Sandbox".
5. Select "Pismo za objavu": "Latinica".
6. Submit.
7. **Expected**:
   - Approved items transition to "Published".
   - AuditLog rows created for each published item.
   - Rejected items stay "Rejected" (not published).
   - First browser: Batch detail now shows all approved items as "Objavljeno" (Published).

### 3e. Download outputs

1. In the batch detail page, look for download links: descriptions.csv and review_queue.json.
2. Download both.
3. **Expected**:
   - descriptions.csv contains rows for all published items (both ćirilica and latinica columns).
   - review_queue.json contains the final state of all items (statuses, reasons, provenance).

### 3f. Verify org isolation (404 on cross-org access)

1. Note the batch URL: `https://<KORPUS_DOMAIN>/app/test-org/batches/<batch_id>/`
2. Create a second org and user the same way.
3. Log in as the second user.
4. **Expected**: Second user lands on their own org dashboard.
5. Try to access the first batch's URL (change org_slug to "test-org" in the URL).
6. **Expected**: 404 (not 403 — org existence is never leaked).

## 4. Admin verification

1. Log in to `/admin/`.
2. Under Accounts, confirm:
   - Org row created.
   - User row exists.
   - Membership row links the two.
3. Under Batches, confirm:
   - Batch row shows upload date, status "completed", item counts.
   - ReviewItem rows: multiple items with statuses (pending, approved, rejected, published).
   - AuditLog rows: one for each action (approve, reject, publish, publish_failed if any).
4. Under Leads, confirm:
   - Lead row from step 2 (contact form submission).
5. **Expected**: All rows present and correct.

## 5. CLI workflow (unchanged from Phase 1)

1. Prepare a test CSV: 3–5 products with brand (e.g., Nike, iPhone), color, size, material.
2. Run:
   ```bash
   python -m pipeline.cli generate <csv_path> -o /tmp/test-gen --fake
   ```
3. **Expected**:
   - `/tmp/test-gen/descriptions.csv` created with dual-script output.
   - `/tmp/test-gen/provenance/` directory contains claim mappings.
   - `/tmp/test-gen/review_queue.json` created with all items PENDING.
4. Approve one item:
   ```bash
   python -m pipeline.cli review approve <product_id> -o /tmp/test-gen
   ```
5. **Expected**: `review_queue.json` updated; item status → APPROVED.
6. Reject another:
   ```bash
   python -m pipeline.cli review reject <product_id> -o /tmp/test-gen --reason "bad copy"
   ```
7. **Expected**: `review_queue.json` updated; item status → REJECTED with reason.
8. Run WooCommerce publish (against sandbox credentials from env vars):
   ```bash
   KORPUS_CONSUMER_KEY=<key> KORPUS_CONSUMER_SECRET=<secret> \
   python -m pipeline.cli publish -o /tmp/test-gen --connector woocommerce \
     --base-url https://sandbox.example.com
   ```
9. **Expected**: Approved items transitioned to PUBLISHED; rejected items skipped.

## 6. Domestic connectors (Selltico, TAU)

1. In the batch detail page, publish to "Selltico" or "TAU Commerce" (if credentials exist; if not, create dummy ones in admin).
2. **Expected**: Publishing attempts to push; connector raises `NotImplementedError` loudly:
   - Items stay APPROVED (not transitioned to PUBLISHED).
   - AuditLog row created: action="publish_failed", detail notes "connector not implemented".
   - No silent failures.

## 7. Transliteration spot-check (0% error on protected terms)

1. Generate a batch with a CSV containing brand names (iPhone, Nike, Samsung) or model numbers.
2. Review the output in `/tmp/test-gen/descriptions.csv` or the batch detail page.
3. **Expected**:
   - Latinica column: iPhone, Nike, Samsung unchanged.
   - Ćirilica column: Same brand names still iPhone, Nike, Samsung (NOT ајПхоне, Нике, etc.).
   - Regular Serbian nouns (e.g., "patika" → "патика") transliterate correctly.

## 8. Rate limiting — login

1. Try logging in to `/app/login/` with an invalid password 11 times rapidly (same IP, same account).
2. **Expected**: After ~5 failed attempts, HTTP 429 response; login page re-rendered with Serbian error message (generic, no account-exists leak).

## 9. Rate limiting — lead form

1. Submit the landing page contact form 6 times in quick succession (same IP, within 1 hour).
2. **Expected**: 7th submission returns 429; no spurious Lead rows created.

## 10. Final summary

- [ ] Landing page renders offline, scripts toggle correctly, brands stay protected.
- [ ] Lead form submits, notification email sent, Lead row in admin.
- [ ] Org + user + membership created.
- [ ] Batch uploads (Test provider), generates, completes.
- [ ] Review queue loads, approve/reject works, AuditLog rows created.
- [ ] Publish to WooCommerce succeeds; items marked PUBLISHED; descriptions.csv and review_queue.json download.
- [ ] Second org user cannot view first org's batches (404).
- [ ] Admin shows all rows (org, user, membership, batch, items, audit logs, leads).
- [ ] CLI workflow unchanged: generate → review → publish works offline (--fake).
- [ ] Selltico/TAU publish attempts fail with NotImplementedError (expected).
- [ ] Transliteration: brand names (iPhone, Nike) untouched in ćirilica.
- [ ] Login rate limit: 11 attempts → 429 after 5/min bucket fills.
- [ ] Lead form rate limit: 6th submission within 1h → 429.

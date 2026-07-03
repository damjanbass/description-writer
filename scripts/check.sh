#!/usr/bin/env bash
# scripts/check.sh -- the single verification gate for this repo.
#
# Runs, in order, fail-fast on the first failure:
#   1. Engine unit tests       (python -m pytest -q)
#   2. Lint                    (python -m ruff check .)
#   3. Django (web/) tests     (manage.py test batches accounts leads connections)
#   4. Production deploy check (manage.py check --deploy), with stub secrets
#      set ONLY for that one step, in a subshell so nothing leaks into the
#      calling shell's environment.
#
# Mirror of scripts/check.ps1 for the Windows dev box -- keep both in sync.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python}"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

banner() {
  echo ""
  echo "======================================================================"
  echo "== $1"
  echo "======================================================================"
}

# Last non-blank line of a file -- used to pull a one-line summary out of
# pytest/manage.py output without re-parsing their full logs.
last_nonblank_line() {
  awk 'NF{line=$0} END{print line}' "$1"
}

banner "1/4 Engine tests -- \$PYTHON -m pytest -q"
"$PYTHON" -m pytest -q 2>&1 | tee "$WORK_DIR/pytest.log"
PYTEST_SUMMARY="$(last_nonblank_line "$WORK_DIR/pytest.log")"

banner "2/4 Lint -- \$PYTHON -m ruff check ."
"$PYTHON" -m ruff check . 2>&1 | tee "$WORK_DIR/ruff.log"
if [ -s "$WORK_DIR/ruff.log" ]; then
  RUFF_SUMMARY="$(last_nonblank_line "$WORK_DIR/ruff.log")"
else
  RUFF_SUMMARY="no issues"
fi

banner "3/4 Web tests -- \$PYTHON web/manage.py test batches accounts leads connections -v 0"
"$PYTHON" web/manage.py test batches accounts leads connections -v 0 2>&1 | tee "$WORK_DIR/webtest.log"
WEBTEST_SUMMARY="$(grep -E '^(Ran|OK|FAILED)' "$WORK_DIR/webtest.log" | tr '\n' ' ')"
WEBTEST_SUMMARY="${WEBTEST_SUMMARY:-OK}"

banner "4/4 Deploy check -- manage.py check --deploy --settings=config.settings.prod"
# Stub secrets exist ONLY inside this subshell's environment -- the
# parenthesized subshell means these `export`s never touch the calling
# shell, so nothing leaks past this one step.
STUB_SECRET_KEY="$("$PYTHON" -c "import secrets; print(secrets.token_urlsafe(64))")"
STUB_FERNET_KEY="$("$PYTHON" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
(
  export KORPUS_SECRET_KEY="$STUB_SECRET_KEY"
  export KORPUS_ALLOWED_HOSTS="korpus.check.invalid"
  export KORPUS_CSRF_TRUSTED_ORIGINS="https://korpus.check.invalid"
  export POSTGRES_PASSWORD="check-deploy-stub-password"
  export KORPUS_FERNET_KEY="$STUB_FERNET_KEY"
  "$PYTHON" web/manage.py check --deploy --settings=config.settings.prod
) 2>&1 | tee "$WORK_DIR/deploycheck.log"
DEPLOYCHECK_SUMMARY="$(last_nonblank_line "$WORK_DIR/deploycheck.log")"

banner "ALL CHECKS PASSED"
echo "Engine tests : ${PYTEST_SUMMARY}"
echo "Lint         : ${RUFF_SUMMARY}"
echo "Web tests    : ${WEBTEST_SUMMARY}"
echo "Deploy check : ${DEPLOYCHECK_SUMMARY}"

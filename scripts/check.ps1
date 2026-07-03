<#
.SYNOPSIS
    scripts/check.ps1 -- the single verification gate for this repo
    (Windows dev box). Mirrors scripts/check.sh -- keep both in sync.

.DESCRIPTION
    Runs, in order, fail-fast on the first failure:
      1. Engine unit tests       (python -m pytest -q)
      2. Lint                    (python -m ruff check .)
      3. Django (web/) tests     (manage.py test batches accounts leads connections)
      4. Production deploy check (manage.py check --deploy), with stub secrets
         set ONLY for that one step and restored afterward.

    Native commands are invoked without merging stderr into the success
    stream (no `2>&1`): in Windows PowerShell 5.1 that wraps every stderr
    line in a NativeCommandError and falsifies `$?` even on success, so this
    script relies on `$LASTEXITCODE` for fail-fast instead, and only tees
    stdout (safe -- untouched stderr still prints straight to the console).
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if ($env:PYTHON) {
    $Python = $env:PYTHON
} else {
    $VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $Python = $VenvPython
    } else {
        $Python = "python"
    }
}

function Write-Banner([string]$Title) {
    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host "== $Title"
    Write-Host ("=" * 70)
}

function Get-LastNonBlankLine {
    param([string[]]$Lines)
    for ($i = $Lines.Count - 1; $i -ge 0; $i--) {
        if ($Lines[$i] -and $Lines[$i].Trim().Length -gt 0) {
            return $Lines[$i].Trim()
        }
    }
    return ""
}

function Stop-OnFailure([string]$Description) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "FAILED: $Description (exit code $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# -- 1/4 Engine tests ---------------------------------------------------------
Write-Banner "1/4 Engine tests -- $Python -m pytest -q"
& $Python -m pytest -q | Tee-Object -Variable pytestLines
Stop-OnFailure "engine tests (pytest)"
$pytestSummary = Get-LastNonBlankLine $pytestLines

# -- 2/4 Lint ------------------------------------------------------------------
Write-Banner "2/4 Lint -- $Python -m ruff check ."
& $Python -m ruff check . | Tee-Object -Variable ruffLines
Stop-OnFailure "lint (ruff check .)"
if ($ruffLines -and $ruffLines.Count -gt 0) {
    $ruffSummary = Get-LastNonBlankLine $ruffLines
} else {
    $ruffSummary = "no issues"
}

# -- 3/4 Web tests ---------------------------------------------------------
Write-Banner "3/4 Web tests -- $Python web/manage.py test batches accounts leads connections -v 0"
& $Python web/manage.py test batches accounts leads connections -v 0
Stop-OnFailure "web tests (manage.py test)"
# Django's test runner writes its "Ran N tests ... OK" summary to stderr, so
# it isn't cheaply capturable without the stderr-redirection pitfall noted
# above -- it already printed straight to the console above.
$webTestSummary = "OK (exit code 0; summary above)"

# -- 4/4 Deploy check ------------------------------------------------------
Write-Banner "4/4 Deploy check -- manage.py check --deploy --settings=config.settings.prod"
$stubSecretKey = & $Python -c "import secrets; print(secrets.token_urlsafe(64))"
$stubFernetKey = & $Python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

$stubVars = [ordered]@{
    KORPUS_SECRET_KEY           = $stubSecretKey
    KORPUS_ALLOWED_HOSTS        = "korpus.check.invalid"
    KORPUS_CSRF_TRUSTED_ORIGINS = "https://korpus.check.invalid"
    POSTGRES_PASSWORD           = "check-deploy-stub-password"
    KORPUS_FERNET_KEY           = $stubFernetKey
}

# Stub secrets exist ONLY in the process environment for the duration of this
# one command, and are always restored/unset in the `finally` block below --
# even if the deploy check itself fails.
$envBackup = @{}
foreach ($name in $stubVars.Keys) {
    $envBackup[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
    [System.Environment]::SetEnvironmentVariable($name, $stubVars[$name], "Process")
}

$deployExitCode = 0
try {
    & $Python web/manage.py check --deploy --settings=config.settings.prod | Tee-Object -Variable deployLines
    $deployExitCode = $LASTEXITCODE
} finally {
    foreach ($name in $stubVars.Keys) {
        [System.Environment]::SetEnvironmentVariable($name, $envBackup[$name], "Process")
    }
}

if ($deployExitCode -ne 0) {
    Write-Host ""
    Write-Host "FAILED: deploy check (exit code $deployExitCode)" -ForegroundColor Red
    exit $deployExitCode
}
$deploySummary = Get-LastNonBlankLine $deployLines

# -- Summary -----------------------------------------------------------------
Write-Banner "ALL CHECKS PASSED"
Write-Host "Engine tests : $pytestSummary"
Write-Host "Lint         : $ruffSummary"
Write-Host "Web tests    : $webTestSummary"
Write-Host "Deploy check : $deploySummary"

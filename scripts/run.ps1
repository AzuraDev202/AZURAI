$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe' -PathType Leaf) -or
    -not (Test-Path -LiteralPath '.venv\pyvenv.cfg' -PathType Leaf)) {
    throw 'Python environment is missing or incomplete. Run setup.ps1 first.'
}
if ('--help' -notin $args -and '-h' -notin $args) {
    & '.\.venv\Scripts\python.exe' scripts/start_database.py
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL is unavailable. See the message above.' }
}
& '.\.venv\Scripts\python.exe' -m azurai @args
exit $LASTEXITCODE

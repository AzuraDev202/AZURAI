$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe' -PathType Leaf) -or
    -not (Test-Path -LiteralPath '.venv\pyvenv.cfg' -PathType Leaf)) {
    throw 'Python environment is missing or incomplete. Run setup.ps1 first.'
}
& '.\.venv\Scripts\python.exe' -m azurai @args
exit $LASTEXITCODE

# Compatibility entry point; implementation lives in scripts/.
& (Join-Path $PSScriptRoot 'scripts\run.ps1') @args
exit $LASTEXITCODE

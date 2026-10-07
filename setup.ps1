# Compatibility entry point; implementation lives in scripts/.
& (Join-Path $PSScriptRoot 'scripts\setup.ps1') @args
exit $LASTEXITCODE

param([ValidateSet('cpu', 'cuda')][string]$Flavor = 'cuda')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
if (-not (Test-Path '.desktop-venv\Scripts\python.exe')) {
    python -m venv .desktop-venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create build environment.' }
}
$python = Join-Path $PSScriptRoot '.desktop-venv\Scripts\python.exe'
$index = if ($Flavor -eq 'cuda') { 'https://download.pytorch.org/whl/cu118' } else { 'https://download.pytorch.org/whl/cpu' }
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $python -m pip install --force-reinstall torch==2.7.1 torchvision==0.22.1 --index-url $index
if ($LASTEXITCODE -ne 0) { throw 'PyTorch install failed.' }
& $python -m pip install -r requirements-desktop.txt
if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency install failed.' }
& $python -m PyInstaller --clean --noconfirm desktop/AZURAI.spec
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
& '.\dist\AZURAI\AZURAI.exe' --smoke-test | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Frozen app smoke test failed.' }
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($iscc) {
    & $iscc.Source "/DFlavor=$Flavor" desktop/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
}
Write-Host "Built dist\AZURAI\AZURAI.exe ($Flavor). Keep the entire AZURAI folder together."

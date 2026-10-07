$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'

function Test-ProjectEnvironment {
    if (-not (Test-Path -LiteralPath '.venv\pyvenv.cfg' -PathType Leaf) -or
        -not (Test-Path -LiteralPath '.venv\Scripts\python.exe' -PathType Leaf)) {
        return $false
    }
    $savedErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & '.\.venv\Scripts\python.exe' -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $savedErrorPreference
    }
}

if (-not (Test-ProjectEnvironment)) {
    Write-Host 'Creating or repairing the project Python environment...'
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create or repair .venv. Stop the running UI/Python processes and run setup.ps1 again.'
    }
    if (-not (Test-ProjectEnvironment)) { throw 'Python environment is still invalid after repair.' }
}
& '.\.venv\Scripts\python.exe' -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) { throw 'Could not bootstrap pip.' }
& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not upgrade pip.' }
& '.\.venv\Scripts\python.exe' -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu118
if ($LASTEXITCODE -ne 0) { throw 'Could not install PyTorch CUDA.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies.' }
Write-Host 'Setup complete. Run: .\run.ps1'

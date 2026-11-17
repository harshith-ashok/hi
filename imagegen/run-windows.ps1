# Sets up and runs the image service on the Windows tailscale box (NVIDIA GPU). Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File imagegen\run-windows.ps1 -Key <secret>
# The first run creates imagegen\.venv, installs CUDA torch and diffusers, and opens port 8790 to Tailscale only.
param(
    [string]$Key = $env:IMAGE_API_KEY,
    [string]$Model = "Tongyi-MAI/Z-Image-Turbo",
    [string]$TorchIndex = "https://download.pytorch.org/whl/cu128"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not $Key) { throw "Pass -Key <secret> (the same value as IMAGE_API_KEY on the Mac)." }

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating the virtual environment..."
    python -m venv .venv
}
& $py -c "import torch, diffusers" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing CUDA torch and diffusers (several GB)..."
    & $py -m pip install --upgrade pip
    & $py -m pip install torch --index-url $TorchIndex
    & $py -m pip install -r requirements.txt
}
& $py -c "import torch,sys; print('CUDA available:', torch.cuda.is_available()); sys.exit(0 if torch.cuda.is_available() else 1)"
if ($LASTEXITCODE -ne 0) { throw "torch cannot see the GPU. Reinstall with a CUDA build: $py -m pip install --force-reinstall torch --index-url $TorchIndex" }

if (-not (Get-NetFirewallRule -DisplayName "hi imagegen" -ErrorAction SilentlyContinue)) {
    try {
        New-NetFirewallRule -DisplayName "hi imagegen" -Direction Inbound -Protocol TCP -LocalPort 8790 -Action Allow -Profile Any -RemoteAddress 100.64.0.0/10 | Out-Null
        Write-Host "Opened port 8790 to the tailnet."
    } catch { Write-Warning "Could not open the firewall (run once as administrator): $_" }
}

$env:IMAGE_API_KEY = $Key
$env:IMAGE_MODEL = $Model
Write-Host "Starting the image service on :8790 (the first picture downloads the model and takes minutes)..."
& $py server.py

# Beat Markers installer: sets up the analyzer environment and adds the scripts to Resolve's menu.
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1 [-BeatThis]
param([switch]$BeatThis)
$ErrorActionPreference = "Stop"

$Repo     = $PSScriptRoot
$Data     = Join-Path $env:LOCALAPPDATA "BeatMarkers"
$App      = Join-Path $Data "app"
$Venv     = Join-Path $Data "venv"
$Menu     = Join-Path $env:APPDATA "Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\Beat Markers"
$Config   = Join-Path $Data "config.json"

function Invoke-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) { & uv @args }
    else { & py -m uv @args }
    if ($LASTEXITCODE -ne 0) { throw "uv $($args -join ' ') failed" }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (Python environment manager)..."
    & py -m pip install --user --quiet uv
    if ($LASTEXITCODE -ne 0) { throw "Couldn't install uv. Install it from https://docs.astral.sh/uv/ and re-run." }
}

Write-Host "Creating analyzer environment in $Venv ..."
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    Invoke-Uv venv --python cpython-3.13-windows-x86_64 $Venv
}
$Py = Join-Path $Venv "Scripts\python.exe"
Invoke-Uv pip install --python $Py -r (Join-Path $Repo "requirements.txt")
if ($BeatThis) {
    Write-Host "Installing beat_this (neural beat/downbeat tracker, downloads PyTorch)..."
    Invoke-Uv pip install --python $Py torch --index-url https://download.pytorch.org/whl/cpu
    Invoke-Uv pip install --python $Py "beat_this @ git+https://github.com/CPJKU/beat_this.git"
}

Write-Host "Copying app files..."
New-Item -ItemType Directory -Force $App, $Menu | Out-Null
Remove-Item -Recurse -Force (Join-Path $App "beatmarkers") -ErrorAction SilentlyContinue
Copy-Item -Recurse (Join-Path $Repo "beatmarkers") $App
Get-ChildItem (Join-Path $App "beatmarkers") -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item (Join-Path $Repo "launchers\*.py") $Menu -Force

$settings = @{ python = (Join-Path $Venv "Scripts\pythonw.exe"); engine = "librosa"; marker_origin = "source" }
if (Test-Path $Config) {
    (Get-Content $Config -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $settings[$_.Name] = $_.Value }
}
$settings.python = Join-Path $Venv "Scripts\pythonw.exe"
if ($BeatThis) { $settings.engine = "beat_this" }
[IO.File]::WriteAllText($Config, ($settings | ConvertTo-Json))

# Resolve itself needs a 64-bit Python on the system to run .py scripts at all.
$found = @()
$best = $null
foreach ($root in "HKLM:\SOFTWARE\Python\PythonCore", "HKCU:\SOFTWARE\Python\PythonCore") {
    if (Test-Path $root) {
        Get-ChildItem $root | Where-Object { $_.PSChildName -notmatch "-32$" } | ForEach-Object {
            $exe = (Get-ItemProperty (Join-Path $_.PSPath "InstallPath") -ErrorAction SilentlyContinue).ExecutablePath
            if ($exe -and (Test-Path $exe)) {
                $found += "$($_.PSChildName) ($exe)"
                if (-not $best) { $best = Split-Path $exe }
            }
        }
    }
}

Write-Host ""
Write-Host "Beat Markers installed. In Resolve: Workspace > Scripts > Beat Markers" -ForegroundColor Green
if ($found.Count -eq 0) {
    Write-Host ""
    Write-Host "WARNING: no 64-bit Python found. Resolve can't run Python scripts without one." -ForegroundColor Yellow
    Write-Host "Install it for all users, then restart Resolve:" -ForegroundColor Yellow
    Write-Host "  winget install --id Python.Python.3.13 --scope machine --architecture x64" -ForegroundColor Yellow
} else {
    Write-Host "64-bit Python for Resolve: $($found -join ', ')"
    # Resolve may otherwise pick a newer 32-bit Python and silently fail to run any .py script.
    $current = [Environment]::GetEnvironmentVariable("PYTHON3HOME", "User")
    if (-not $current -or -not (Test-Path (Join-Path $current "python3.dll"))) {
        [Environment]::SetEnvironmentVariable("PYTHON3HOME", $best.TrimEnd("\"), "User")
        Write-Host "Set PYTHON3HOME=$($best.TrimEnd('\')) so Resolve uses it. Restart Resolve." -ForegroundColor Yellow
    }
}

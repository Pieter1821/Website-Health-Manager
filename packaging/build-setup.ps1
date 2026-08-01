# Build WebsiteHealthManager.exe + Windows Setup installer.
# Requires: Python venv with pyinstaller; optional Inno Setup 6 (iscc).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    throw "Create a venv first: python -m venv .venv && .\.venv\Scripts\pip install -e `".[dev]`" pyinstaller"
}

& $VenvPy -m pip install -q pyinstaller
& $VenvPy (Join-Path $Root "packaging\make_icon.py")
& $VenvPy -m PyInstaller --noconfirm (Join-Path $Root "packaging\whm.spec")

$Exe = Join-Path $Root "dist\WebsiteHealthManager.exe"
if (-not (Test-Path $Exe)) {
    throw "PyInstaller did not produce $Exe"
}
Write-Host "Built $Exe"

$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $Iscc) {
    Write-Host ""
    Write-Host "Inno Setup not found — exe is ready at dist\WebsiteHealthManager.exe"
    Write-Host "Install Inno Setup 6 from https://jrsoftware.org/isinfo.php then re-run this script"
    Write-Host "or compile packaging\whm-setup.iss from the Inno Setup Compiler."
    exit 0
}

& $Iscc (Join-Path $Root "packaging\whm-setup.iss")
$Setup = Get-ChildItem (Join-Path $Root "dist") -Filter "WebsiteHealthManager-Setup-*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($Setup) {
    Write-Host "Installer: $($Setup.FullName)"
} else {
    Write-Host "iscc finished — check dist\ for WebsiteHealthManager-Setup-*.exe"
}

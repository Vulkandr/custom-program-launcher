# build.ps1 - Builds both the portable exe and the installer for Custom Program Launcher.
#
# Usage:
#   .\build.ps1
#
# If Inno Setup is installed somewhere other than the default location, pass its path:
#   .\build.ps1 -InnoCompiler "D:\Some\Other\Path\ISCC.exe"
#
# Note: this builds PyInstaller twice - once as --onefile (for the portable download,
# kept as a true single file) and once as --onedir (bundled into the installer). The
# installer already produces multiple files on disk once installed (totally normal for
# Windows apps), so using --onedir there avoids PyInstaller's onefile temp-extraction
# bug entirely for anyone using the installed version.

param(
    [string]$InnoCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Read version from version.txt (single source of truth)
# ---------------------------------------------------------------------------
$version = (Get-Content "version.txt" -Raw).Trim()
Write-Host "`nBuilding Custom Program Launcher v$version`n" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# Locate the sv_ttk package (needed for --add-data)
# ---------------------------------------------------------------------------
$svTtkPath = (python -c "import sv_ttk, os; print(os.path.dirname(sv_ttk.__file__))").Trim()
if (-not $svTtkPath -or -not (Test-Path $svTtkPath)) {
    Write-Error "Could not locate the sv_ttk package. Is it installed? (pip install sv-ttk pywinstyles)"
    exit 1
}

# ---------------------------------------------------------------------------
# Step 1: Build the portable exe with PyInstaller (--onefile)
# ---------------------------------------------------------------------------
Write-Host "Step 1/3: Building portable exe (--onefile)..." -ForegroundColor Cyan

pyinstaller --onefile --windowed --noupx --name "ProgramLauncher" --icon="app_icon.ico" `
    --distpath "dist\portable" `
    --add-data "app_icon.ico;." `
    --add-data "version.txt;." `
    --add-data "$svTtkPath;sv_ttk" `
    launcher.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller (onefile) build failed."
    exit 1
}

$versionFolder = "Installer_Output\v$version"
New-Item -ItemType Directory -Force -Path $versionFolder | Out-Null

$portableName = "CPL_Portable_v$version.exe"
Copy-Item "dist\portable\ProgramLauncher.exe" "$versionFolder\$portableName" -Force
Write-Host "Portable exe created: $versionFolder\$portableName`n" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 2: Build the folder version with PyInstaller (--onedir), for the installer
# ---------------------------------------------------------------------------
Write-Host "Step 2/3: Building app folder for the installer (--onedir)..." -ForegroundColor Cyan

pyinstaller --onedir --windowed --noupx --name "ProgramLauncher" --icon="app_icon.ico" `
    --distpath "dist\installer" `
    --add-data "app_icon.ico;." `
    --add-data "version.txt;." `
    --add-data "$svTtkPath;sv_ttk" `
    launcher.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller (onedir) build failed."
    exit 1
}

Write-Host "App folder created: dist\installer\ProgramLauncher\`n" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 3: Build the installer with Inno Setup
# ---------------------------------------------------------------------------
Write-Host "Step 3/3: Building installer with Inno Setup..." -ForegroundColor Cyan

if (-not (Test-Path $InnoCompiler)) {
    Write-Error "Inno Setup compiler not found at '$InnoCompiler'. Pass -InnoCompiler <path> if it's installed elsewhere."
    exit 1
}

& $InnoCompiler "CPL_installer.iss"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup compile failed."
    exit 1
}

Write-Host "`nDone! Both files are in $versionFolder\:" -ForegroundColor Green
Write-Host "  - $portableName (portable, single file)" -ForegroundColor Green
Write-Host "  - CPL_Setup_v$version.exe (installer)" -ForegroundColor Green

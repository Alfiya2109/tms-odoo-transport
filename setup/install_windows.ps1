# ==============================================================
#  TMS Odoo - Windows Auto Installer
#  Run this as Administrator in PowerShell
#  Usage: .\setup\install_windows.ps1
# ==============================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  TMS Odoo - Auto Setup Script (Windows)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# --- Check Administrator ---
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "[ERROR] Please run this script as Administrator!" -ForegroundColor Red
    Write-Host "  Right-click PowerShell -> Run as Administrator" -ForegroundColor Yellow
    exit 1
}

# --- Check winget ---
Write-Host "[1/5] Checking winget (Windows Package Manager)..." -ForegroundColor Yellow
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] winget not found. Please install it from Microsoft Store." -ForegroundColor Red
    Start-Process "https://aka.ms/getwinget"
    exit 1
}
Write-Host "      winget found!" -ForegroundColor Green

# --- Install Git ---
Write-Host ""
Write-Host "[2/5] Installing Git..." -ForegroundColor Yellow
$gitCheck = Get-Command git -ErrorAction SilentlyContinue
if ($gitCheck) {
    Write-Host "      Git already installed: $((git --version))" -ForegroundColor Green
} else {
    winget install --id Git.Git -e --source winget --silent
    Write-Host "      Git installed!" -ForegroundColor Green
}

# --- Install Odoo 18 ---
Write-Host ""
Write-Host "[3/5] Checking Odoo 18 Installation..." -ForegroundColor Yellow
$odooPath = "C:\Program Files\Odoo 18.0*"
if (Test-Path $odooPath) {
    Write-Host "      Odoo 18 already installed!" -ForegroundColor Green
} else {
    Write-Host "      Odoo 18 not found. Opening download page..." -ForegroundColor Yellow
    Write-Host "      Please download and install Odoo 18 Community from:" -ForegroundColor White
    Write-Host "      https://www.odoo.com/page/download" -ForegroundColor Cyan
    Start-Process "https://www.odoo.com/page/download"
    Write-Host ""
    Read-Host "      After installing Odoo, press Enter to continue..."
}

# --- Install Java JDK (for mobile stack) ---
Write-Host ""
Write-Host "[4/5] Installing Java JDK 11 (for mobile API)..." -ForegroundColor Yellow
$javaCheck = Get-Command java -ErrorAction SilentlyContinue
if ($javaCheck) {
    Write-Host "      Java already installed: $((java -version 2>&1 | Select-Object -First 1))" -ForegroundColor Green
} else {
    winget install --id EclipseAdoptium.Temurin.11.JDK -e --source winget --silent
    Write-Host "      Java JDK 11 installed!" -ForegroundColor Green
}

# --- Configure Odoo with TMS module ---
Write-Host ""
Write-Host "[5/5] Configuring Odoo with TMS custom addons..." -ForegroundColor Yellow

# Find Odoo installation
$odooInstallDir = Get-ChildItem "C:\Program Files" -Directory | Where-Object { $_.Name -like "Odoo 18*" } | Select-Object -First 1
if ($odooInstallDir) {
    $odooConfPath = "$($odooInstallDir.FullName)\server\odoo.conf"
    $currentDir = (Get-Location).Path
    $addonsPath = "$currentDir\custom_addons"

    if (Test-Path $odooConfPath) {
        $confContent = Get-Content $odooConfPath -Raw

        if ($confContent -notmatch [regex]::Escape($addonsPath)) {
            # Add our custom addons path
            $confContent = $confContent -replace "(addons_path\s*=\s*[^\r\n]+)", "`$1,$addonsPath"
            Set-Content $odooConfPath $confContent
            Write-Host "      TMS addons path added to odoo.conf!" -ForegroundColor Green
            Write-Host "      Path: $addonsPath" -ForegroundColor Cyan
        } else {
            Write-Host "      TMS addons path already in odoo.conf!" -ForegroundColor Green
        }

        # Restart Odoo service
        Write-Host ""
        Write-Host "      Restarting Odoo service..." -ForegroundColor Yellow
        $odooService = Get-Service | Where-Object { $_.Name -like "*odoo*" } | Select-Object -First 1
        if ($odooService) {
            Restart-Service $odooService.Name
            Write-Host "      Odoo service restarted!" -ForegroundColor Green
        }
    }
} else {
    Write-Host "      [SKIP] Odoo not found. Please install Odoo first." -ForegroundColor Yellow
}

# --- Done ---
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next Steps:" -ForegroundColor White
Write-Host "  1. Open browser: http://localhost:8069" -ForegroundColor Cyan
Write-Host "  2. Login: admin / admin" -ForegroundColor Cyan
Write-Host "  3. Go to Apps -> Update App List" -ForegroundColor Cyan
Write-Host "  4. Search 'Transport Management' -> Install" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Need help? Contact: alfiyakhan0921@gmail.com" -ForegroundColor Yellow
Write-Host ""

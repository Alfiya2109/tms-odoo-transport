if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

Write-Host "Fixing Odoo Configuration..."
$confPath = "C:\Program Files\Odoo 18.0.20260615\server\odoo.conf"
$content = Get-Content $confPath
$content = $content -replace "db_name = False", "db_name = Alfiya"
$content = $content -replace "db_name\s*=.*", "db_name = Alfiya"
Set-Content -Path $confPath -Value $content

Write-Host "Restarting Odoo Service..."
Restart-Service -Name "odoo-server-18.0" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "====================================================="
Write-Host "SUCCESS! Odoo configuration fixed permanently!"
Write-Host "====================================================="
Write-Host ""

Write-Host "Press any key to close this window..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

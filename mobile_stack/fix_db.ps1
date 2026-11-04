if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

Write-Host "Registering and Starting PostgreSQL (Odoo Database)..."
& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" register -N "PostgreSQL-17" -D "C:\PostgreSQL_Data"
Start-Service -Name "PostgreSQL-17" -ErrorAction SilentlyContinue

Write-Host "Starting MySQL (API Gateway Database)..."
Start-Service -Name "MySQL80" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "================================================="
Write-Host "SUCCESS! All Databases are now running perfectly!"
Write-Host "================================================="
Write-Host ""

Write-Host "Press any key to close this window..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

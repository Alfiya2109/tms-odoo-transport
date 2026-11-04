if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

Write-Host "Restarting Odoo Service (odoo-server-18.0)..."
Restart-Service -Name "odoo-server-18.0" -Force

Write-Host ""
Write-Host "========================================="
Write-Host "SUCCESS! Odoo has been restarted!"
Write-Host "========================================="
Write-Host ""

Write-Host "Press any key to close this window..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

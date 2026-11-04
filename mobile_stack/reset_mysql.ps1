if (!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

Start-Transcript -Path "C:\Users\Admin\TMS new client project2\mobile_stack\mysql_setup.log" -Force

Write-Host "Stopping MySQL Service..."
Stop-Service -Name "MySQL80" -Force -ErrorAction SilentlyContinue

$mysqlBin = "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe"
$mysqlClient = "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"
$setupScript = "C:\Users\Admin\TMS new client project2\mobile_stack\setup.sql"

# Create an init file to reset root password and create isotrax user safely
$initFile = "C:\Users\Admin\TMS new client project2\mobile_stack\init.sql"
@"
ALTER USER 'root'@'localhost' IDENTIFIED BY 'Admin@123';
CREATE USER IF NOT EXISTS 'isotrax'@'localhost' IDENTIFIED BY 'IsoTrax_GW_2026!';
GRANT ALL PRIVILEGES ON *.* TO 'isotrax'@'localhost';
FLUSH PRIVILEGES;
"@ | Out-File -FilePath $initFile -Encoding ASCII

Write-Host "Resetting passwords and creating user using init-file..."
$p = Start-Process -FilePath $mysqlBin -ArgumentList "--defaults-file=`"C:\ProgramData\MySQL\MySQL Server 8.0\my.ini`"", "--init-file=`"$initFile`"", "--console" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 10
Stop-Process -Id $p.Id -Force
Start-Sleep -Seconds 3

Write-Host "Starting normal MySQL Service..."
Start-Service -Name "MySQL80"
Start-Sleep -Seconds 5

Write-Host "Running Database Setup..."
Get-Content $setupScript | & $mysqlClient -u isotrax -pIsoTrax_GW_2026! 2>&1 | Out-Default

Write-Host ""
Write-Host "========================================="
Write-Host "SUCCESS! Database is fully set up!"
Write-Host "========================================="
Write-Host ""
Stop-Transcript

Write-Host "Press any key to close this window..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

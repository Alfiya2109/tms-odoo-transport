@echo off
echo Starting API Gateway (Tomcat)...
start "" "C:\Users\Admin\TMS new client project2\mobile_stack\Start_Tomcat.bat"

echo Starting Mobile App (Ionic)...
start "" "C:\Users\Admin\TMS new client project2\mobile_stack\Start_MobileApp.bat"

echo Both servers are starting in separate windows!
pause

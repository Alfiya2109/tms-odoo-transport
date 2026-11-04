@echo off
echo Starting API Gateway (Tomcat)...
set "JAVA_HOME=C:\Program Files\Java\jdk-20"
set CATALINA_HOME=C:\Users\Admin\TMS new client project2\mobile_stack\apache-tomcat-10.1.18
cd /d "%CATALINA_HOME%\bin"
call startup.bat
echo Tomcat started in a new window!
pause

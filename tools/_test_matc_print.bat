@echo off
out\cmake-http-msvc\tools\matc\Release\matc.exe -p desktop -a opengl -g -t -o out\test-pom.filamat out\test-pom.mat > out\test-pom.log 2>&1
echo exit=%ERRORLEVEL%

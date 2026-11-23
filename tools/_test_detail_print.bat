@echo off
out\cmake-http-msvc\tools\matc\Release\matc.exe -p desktop -a opengl -g -t -o out\test-detail.filamat samples\materials\aiDetailNormal.mat > out\test-detail.log 2>&1
echo exit=%ERRORLEVEL%

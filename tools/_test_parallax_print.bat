@echo off
out\cmake-http-msvc\tools\matc\Release\matc.exe -p desktop -a opengl -g -t -o out\test-parallax.filamat samples\materials\aiParallax.mat > out\test-parallax.log 2>&1
echo exit=%ERRORLEVEL%

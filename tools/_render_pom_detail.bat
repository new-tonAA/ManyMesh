@echo off
set BIN=out\cmake-http-msvc\samples\Release\mm_bench.exe
set MAT=out\cmake-http-msvc\samples\generated\material
set FLAGS=--headless --window-size 960x720 --fixed-timestep=0.0166667 --no-shadows --auto-frame --warmup 5 --measure 5
%BIN% %FLAGS% -m %MAT%\aiDefaultMat.filamat --out out\pom-ref2.png assets\models\monkey\monkey.obj
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiDetailNormal.filamat --detail-normal out\parallax-monkey45\detail-normal.png --normal-strength 1.0 --out out\pom-detail.png out\parallax-monkey45\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-normal out\parallax-monkey45\detail-normal.png --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 0.0 --parallax-layers 8 --out out\pom-detail-p0.png out\parallax-monkey45\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-normal out\parallax-monkey45\detail-normal.png --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 0.5 --parallax-layers 8 --out out\pom-detail-p05.png out\parallax-monkey45\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-normal out\parallax-monkey45\detail-normal.png --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 1.0 --parallax-layers 8 --out out\pom-detail-p1.png out\parallax-monkey45\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-normal out\parallax-monkey45\detail-normal.png --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 2.0 --parallax-layers 8 --out out\pom-detail-p2.png out\parallax-monkey45\selected.ply

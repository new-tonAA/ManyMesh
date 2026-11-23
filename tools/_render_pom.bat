@echo off
set BIN=out\cmake-http-msvc\samples\Release\mm_bench.exe
set MAT=out\cmake-http-msvc\samples\generated\material
set FLAGS=--headless --window-size 960x720 --fixed-timestep=0.0166667 --no-shadows --auto-frame --warmup 20 --measure 60
%BIN% %FLAGS% --out out\pom-ref.png assets\models\monkey\monkey.obj
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiDefaultMat.filamat --out out\pom-lod.png out\parallax-monkey45\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 0.0 --parallax-layers 8 --out out\pom-lod-s0.png out\parallax-monkey45\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 0.5 --parallax-layers 8 --out out\pom-lod-s05.png out\parallax-monkey45\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 1.0 --parallax-layers 8 --out out\pom-lod-s1.png out\parallax-monkey45\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 2.0 --parallax-layers 8 --out out\pom-lod-s2.png out\parallax-monkey45\selected.ply

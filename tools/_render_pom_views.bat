@echo off
set BIN=out\cmake-http-msvc\samples\Release\mm_bench.exe
set MAT=out\cmake-http-msvc\samples\generated\material
set FLAGS=--headless --window-size 960x720 --fixed-timestep=0.0166667 --no-shadows --auto-frame --views 4 --warmup 3 --measure 3
%BIN% %FLAGS% -m %MAT%\aiDefaultMat.filamat --out out\mv-ref.png assets\models\monkey\monkey.obj
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-normal out\parallax-monkey38-uv\detail-normal.png --detail-height out\parallax-monkey38-uv\detail-height.png --parallax-strength 0.0 --parallax-layers 8 --out out\mv-p0.png out\parallax-monkey38-uv\selected.ply
if errorlevel 1 exit /b 1
%BIN% %FLAGS% -m %MAT%\aiParallax.filamat --detail-normal out\parallax-monkey38-uv\detail-normal.png --detail-height out\parallax-monkey38-uv\detail-height.png --parallax-strength 2.0 --parallax-layers 8 --out out\mv-p2.png out\parallax-monkey38-uv\selected.ply

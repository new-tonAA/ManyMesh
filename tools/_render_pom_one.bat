@echo off
out\cmake-http-msvc\samples\Release\mm_bench.exe --headless --window-size 960x720 --fixed-timestep=0.0166667 --no-shadows --auto-frame --warmup 1 --measure 1 -m out\cmake-http-msvc\samples\generated\material\aiParallax.filamat --detail-height out\parallax-monkey45\detail-height.png --parallax-strength 1.0 --parallax-layers 8 --out out\pom-one.png out\parallax-monkey45\selected.ply

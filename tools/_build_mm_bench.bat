@echo off
"D:\visual studio 2022\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build out\cmake-http-msvc --config Release --target mm_bench -- /m:1 /nologo /v:minimal

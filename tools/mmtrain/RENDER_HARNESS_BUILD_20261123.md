# Render Harness Build Record — 2026-11-23

## Result

The current `samples/mm_bench.cpp`, including the FSR1 and TAA-upscaling options, compiled and linked in the existing Windows Vulkan Release build tree. This verifies compilation only. The executable could not be launched under the local Windows Application Control policy, so no runtime, image-quality, or timing result was produced.

## Build receipt

- Repository base commit: `2d417cacdeb545a13e6bfb7192310191e60670d6` (the worktree was dirty).
- Source file SHA-256: `D0AACF8815F727263D472B04CE9D038CF1D573A399D08C8F17DA216BF29DD2D1`.
- Output: `out/cmake-vulkan/samples/Release/mm_bench.exe`, 25,748,480 bytes.
- Output SHA-256: `6CF1A04D96F33BBB7D2400F83ADEA5F1B37CA91D6534B0EEB965B787D5B546FD`.
- Direct target command: `MSBuild.exe out/cmake-vulkan/samples/mm_bench.vcxproj /t:Build /p:BuildProjectReferences=false /p:Configuration=Release`.
- The target compiled `mm_bench.cpp` and `mm_gpu_cut.cpp` and linked successfully against the pre-existing build outputs. It was not a clean or full dependency rebuild.
- MSVC warned that `-fno-rtti` and `-Wl,--gc-sections` are unrecognized Windows options; it reported zero errors.

## Runtime and full-build blockers

- A full CMake target build attempted to regenerate shaders and FilamentApp web resources. Windows Application Control blocked `glslminifier.exe` and `resgen.exe`, so the full dependency graph did not complete.
- Launching the newly linked `mm_bench.exe --help` was also blocked by Windows Application Control.
- No attempt was made to bypass that policy. A successful compile does not show that the new switches work at runtime.

## Next verification

Run the hash-pinned executable on an environment where the project-generated helper executables are permitted. First confirm the command-line options and FSR1/TAA path initialization, then capture matched reference and candidate frames before recording any quality or timing claim. This desktop check still cannot establish mobile-device behavior.

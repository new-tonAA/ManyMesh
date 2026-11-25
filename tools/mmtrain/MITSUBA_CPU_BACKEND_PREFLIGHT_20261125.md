# Mitsuba CPU backend preflight

Checked 2026-11-25 as a local alternative to the frozen CUDA placement
control. **The renderer did not load; no fitting or image scoring was run.**
This is an environment preflight, not an algorithm result.

## Finding

An ignored dependency directory contains Windows CPython 3.12 builds of
Mitsuba 3.9.0 and Dr.Jit 1.4.0, including `scalar_rgb` and `llvm_ad_rgb`
extension modules. Registering the package directories with
`os.add_dll_directory()` allowed Python to load Dr.Jit, but initialization
reported `jitc_llvm_init(): LLVM API initialization failed`. Importing Mitsuba
then failed while loading `mitsuba_ext` with a Windows DLL-load error. The
failure occurred before selecting a variant, rendering, or differentiating.
The cause of the missing runtime dependency was not isolated.

A follow-up local search found no `LLVM*.dll` in the searched Anaconda,
Dev-C++, or Program Files trees. The Anaconda package cache contains
`llvm-openmp`, but not LLVM itself. An LLVM 20.1.8 library is bundled with
`llvmlite`; its Python FFI handle does not expose the LLVM C API entry points
checked (`LLVMContextCreate`, `LLVMGetVersion`, and related symbols). It did
not provide a compatible runtime for this probe.

## Reproduction

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/appearance-mitsuba-pydeps-20261123').Path
python -c "import os,pathlib; root=pathlib.Path(os.environ['PYTHONPATH']); [os.add_dll_directory(str(p)) for p in [root/'drjit',root/'mitsuba']]; import drjit as dr; import mitsuba as mi; print(mi.variants())"
Remove-Item Env:PYTHONPATH
```

The dependency directory is ignored and is not part of the repository; the
command may not reproduce without that local environment. No dependency was
installed or modified during these checks.

## Decision

The original check did not provide a runnable CPU fallback on this Windows
host. It did not replace the frozen nvdiffmodeling experiment or imply a quality
loss. The follow-up below identifies the local application-control block and
links a distinct CPU silhouette-fit result from an Ubuntu hosted runner.

## Follow-up check on 2026-11-25

Visual Studio's x64 LLVM runtime was found at its bundled `LLVM-C.dll`. Setting
`DRJIT_LIBLLVM_PATH` to that file allowed Dr.Jit 1.4.0 to import, but Mitsuba
still could not load `mitsuba_alias.cp312-win_amd64.pyd`. The extension is
unsigned. Windows Code Integrity event 3077 explicitly records `python.exe`
being blocked from loading this file under the active application-control
policy. This is a policy block, not evidence that the CPU renderer requires
CUDA or that the fitted method failed. No settings were changed and no policy
bypass was attempted.

The CPU backend has run on an Ubuntu 24.04 hosted runner in a separate
projective-silhouette experiment. Training loss fell on two reused assets, but
held-out-view LDR-FLIP worsened on both. This does not reproduce the frozen
placement fit. See the [CPU fit report](PROJECTIVE_SILHOUETTE_CPU_20261124.md)
and [workflow](../../.github/workflows/manymesh-projective-cpu.yml).

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

## Reproduction

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = (Resolve-Path 'out/appearance-mitsuba-pydeps-20261123').Path
python -c "import os,pathlib; root=pathlib.Path(os.environ['PYTHONPATH']); [os.add_dll_directory(str(p)) for p in [root/'drjit',root/'mitsuba']]; import drjit as dr; import mitsuba as mi; print(mi.variants())"
Remove-Item Env:PYTHONPATH
```

The dependency directory is ignored and is not part of the repository; the
command may not reproduce without that local environment. No dependency was
installed or modified during this check.

## Decision

This does not provide a runnable CPU differentiable-rendering fallback. It
does not replace the frozen nvdiffmodeling experiment or imply a quality loss.
Use the CUDA protocol on a compatible host, or resolve the Mitsuba runtime and
freeze a separate backend protocol before collecting any fitting results.

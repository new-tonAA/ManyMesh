# CUDA environment recheck

Checked 2026-11-25 while preparing the frozen fixed-topology placement control.
This is an environment preflight only; no fitting or quality scoring occurred.

The default Python 3.12.3 environment uses PyTorch 2.7.1+cpu and reports no CUDA
runtime or device. A second Conda environment, `chartdet`, contains PyTorch
1.13.1 and CUDA 11.7 packages, but importing PyTorch fails with Windows
`WinError 4551`: application control blocks `torch/lib/shm.dll` or a dependency.
CUDA device discovery therefore cannot be tested through that environment.

`nvidia-smi` and `nvcc` are absent from `PATH`; no `nvcc` executable was found
in the secondary environment. `nvdiffrast` is not installed there. Android
`adb` is absent from `PATH`. WSL distro enumeration fails with
`Wsl/EnumerateDistros/Service/E_ACCESSDENIED`. These observations do **not**
prove that the host has no NVIDIA GPU; they show that this workspace currently
has no usable CUDA execution path for the frozen experiment.

The machine-readable observations are in
[`CUDA_ENVIRONMENT_RECHECK_20261125.json`](CUDA_ENVIRONMENT_RECHECK_20261125.json).
The frozen experiment and its stop criteria remain in
[`MANYMESH_NEXT_EXPERIMENT_GATE.md`](../../MANYMESH_NEXT_EXPERIMENT_GATE.md).
Resume only on a host where CUDA-enabled PyTorch imports, a CUDA device is
visible, and the pinned `nvdiffrast` extension can be built. This preflight is
not a negative result for the fitting method.

## CPU fallback recheck

Rechecked the default Python 3.12.3 environment with the ManyMesh research
`PYTHONPATH` active. PyTorch remains `2.7.1+cpu`; CUDA runtime and device are
unavailable. Import probes found none of `nvdiffrast`, PyTorch3D,
`soft_renderer`, Kaolin, JAX, Mitsuba, Dr.Jit, or DEODR. `nvidia-smi`, `nvcc`,
and Blender are not available on `PATH`. This rules out an already-installed
differentiable CPU-renderer fallback in this environment; it does not change
the frozen CUDA protocol or its result status. The earlier DEODR and Mitsuba
build/runtime investigations are documented separately.

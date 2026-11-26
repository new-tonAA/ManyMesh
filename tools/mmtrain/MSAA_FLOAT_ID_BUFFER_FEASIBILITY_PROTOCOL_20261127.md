# D3D12 multisample float-ID feasibility probe

Protocol frozen 2026-11-27 after the `r32uint` attachment was rejected by the
Iris Xe D3D12 backend. This is a separate format-compatibility check for the
same possible in-engine optimizer control, not a quality or performance test.

## Question and decision rule

Can a 4x multisampled `r32float` color attachment retain primitive ID 17 per
sample and expose it to a compute shader? For this probe, ID 17 is exactly
representable in IEEE-754 single precision. Use the same 64x64 one-triangle
render, resolved RGBA color target, four per-pixel samples, and compute readback
as the integer-ID probe. Pass only if pipeline creation and dispatch succeed,
at least one sample equals 17, and all other samples are the cleared value 0.

The integer-ID failure and this float-ID outcome remain separate observations.
Neither result validates a geometry optimizer, quality gain, production API, or
performance. If both formats fail, close these two WebGPU per-sample-ID routes;
this does not rule out native Filament, another format/API, or a single-sample
contributor buffer as a surrogate.

## Frozen environment and reproduction

Use only the Intel Iris Xe D3D12 integrated GPU, the ignored
`out/msaa-quality-venv` environment (`wgpu==0.33.0`), 64x64 resolution, four
samples, and the same generated triangle and integer value 17. Record the
adapter, script hash, package version, sample counts, and exception.

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' `
  tools/mmtrain/probe_msaa_float_id_buffer.py `
  --out out/msaa-float-id-buffer-feasibility-20261127/result.json
```

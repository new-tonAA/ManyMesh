# D3D12 multisample primitive-ID feasibility probe

Protocol frozen 2026-11-27 before the capability result. This is a local
renderer/API feasibility check for a possible Deliot-style in-engine optimizer
control. It is not a geometry-quality experiment, an optimizer implementation,
or a performance claim.

## Question and decision rule

Can this laptop's Intel Iris Xe D3D12 path write primitive IDs into a 4x
multisampled `r32uint` color attachment and read each covered sample from a
compute shader?

Use one generated fullscreen-space triangle with constant ID 17, a 4x MSAA
`rgba8unorm` color target resolved to a single-sample texture, a parallel 4x
MSAA `r32uint` ID target without resolve, and a compute pass that copies all
four ID samples per pixel to a readback buffer. Background samples are cleared
to ID 0. A pass requires successful render/compute pipeline creation, at least
one sample equal to 17, and no nonzero ID other than 17. A validation/API
failure or incorrect output closes this exact WebGPU route; it does not prove
that a native Filament/D3D12 route or another API is infeasible.

## Frozen environment and scope

- Adapter must identify as Intel Iris Xe Graphics, D3D12, and hardware
  `IntegratedGPU`; software adapters are rejected.
- Use the existing ignored `out/msaa-quality-venv` environment and its pinned
  `wgpu` package. Request only `timestamp-query`, matching the existing local
  hardware harness; timestamps are not read by this probe.
- Fixed 64x64 render target, one triangle, one draw, four samples per pixel.
- Record source hash, adapter metadata, package version, observed sample
  counts, and any exception. Do not infer optimizer cost from this synthetic
  scene.

## Reproduction

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' `
  tools/mmtrain/probe_msaa_id_buffer.py `
  --out out/msaa-id-buffer-feasibility-20261127/result.json
```

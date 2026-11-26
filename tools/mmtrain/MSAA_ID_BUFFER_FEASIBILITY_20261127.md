# Per-sample ID buffer feasibility on the local Iris Xe

Completed 2026-11-27. A D3D12/WebGPU `r32uint` multisample ID attachment is
unsupported on this adapter, but a float-encoded ID buffer worked at 4x MSAA.
This establishes one required GPU plumbing step for a possible local
Deliot-style optimizer control. It is not an optimizer, image-quality result,
or performance measurement.

## Results

Both probes used the Intel Iris Xe Graphics integrated GPU, D3D12 backend,
driver 31.0.101.4502, WebGPU `wgpu==0.33.0`, a 64x64 render target, one
generated triangle, four samples per pixel, and constant primitive ID 17.

| ID attachment | Outcome | Observation |
|---|---|---|
| `r32uint` | Unsupported | Device validation rejected texture creation: `Format R32Uint does not support multisampling`. No render or compute pass ran. |
| `r32float` | Pass | A render pass wrote 17 to covered samples; a compute pass loaded all 16,384 sample slots. It read 5,201 covered samples, all equal to 17, with no other nonzero ID. |

The first failed result closes only the direct integer-format route. The float
route demonstrates that the adapter can preserve and expose a small exact ID
per MSAA sample to compute. Because IEEE-754 single precision represents
integers exactly only up to 2^24, this encoding is unsuitable for arbitrary
large global face indices without an explicit bounded/local-ID scheme.

## What this establishes

The non-CUDA local path is viable for an API feasibility prototype: this laptop
can render 4x MSAA and use a compute shader to inspect per-sample contributor
IDs in an auxiliary `r32float` attachment. This is consistent with Deliot et
al.'s in-engine stochastic-gradient approach, which uses ID/UV buffers and
compute shaders rather than requiring CUDA.

It does **not** yet map raster samples to the vertices and parameters that
influence them, estimate or optimize gradients, preserve all contributors at
overlapping/depth-discontinuous edges, run on Filament's production renderer,
or demonstrate a quality improvement. The next feasible step is a
fixed-topology gradient-control prototype on a real asset, followed by a
frozen multi-view quality comparison. It must use the same source reference,
rendering operator, face budget, and image metrics as its non-optimized
control. No CUDA host or neural-network training is needed for this specific
stochastic-gradient route.

## Reproduction and receipts

The two frozen protocols describe the separate format decisions:
[integer format](MSAA_ID_BUFFER_FEASIBILITY_PROTOCOL_20261127.md) and
[float format](MSAA_FLOAT_ID_BUFFER_FEASIBILITY_PROTOCOL_20261127.md). The
runners are [integer probe](probe_msaa_id_buffer.py) and
[float probe](probe_msaa_float_id_buffer.py). Their JSON receipts preserve the
adapter, WGPU version, script hashes, observed samples, and validation failure
or pass: [r32uint](msaa_id_buffer_feasibility_20261127.json),
[r32float](msaa_float_id_buffer_feasibility_20261127.json).

The float probe needed one WGSL typing fix during development (`textureLoad`
returns a vector, so the scalar sample component is `.x`). The recorded pass
uses the final script hash and followed that correction. No code-signing or
Windows security setting was changed.

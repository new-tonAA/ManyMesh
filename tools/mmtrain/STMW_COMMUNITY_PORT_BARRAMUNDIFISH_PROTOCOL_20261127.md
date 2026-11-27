# STMW community-port feasibility screen

Status: frozen before image scoring. This is a one-asset development
comparison, not a reproduction of Liu et al. (TOG 2025) and not confirmation
evidence.

## Question

Does the MIT community TypeScript port of *Simplifying Textured Triangle
Meshes in the Wild* produce a legal 1,932-face geometry on the reused
BarramundiFish development asset, and where does its rendered quality fall
relative to the already-frozen ManyMesh, border-QEM, and meshoptimizer controls?
If the candidate is not exactly 1,932 faces or does not preserve the source
boundary, exclude it before image scoring. This screen does not decide whether
the port is a faithful implementation of the paper.

## Frozen input and method

- Source: Khronos BarramundiFish, CC0, geometry-only OBJ
  `out/appearance-asset-intake-20261124/BarramundiFish/geometry.obj`;
  SHA-256 `6cbce9b89fd5315929c19582afe1949502f3ea4e5705c569c6acc884b410c949`.
  It has 2,188 vertices and 3,864 triangles, with no open boundary edges.
- The input adapter is `tools/mmtrain/obj_to_geometry_glb.py`. Its GLB output
  is SHA-256
  `5ae54a20bfc4f56a65560ee54f0fc253a499d0b16e42c1ce2484f6b2ef9cd843`.
- Community implementation:
  [illusioneering/textured-mesh-simplification](https://github.com/illusioneering/textured-mesh-simplification),
  commit `3b9195cb75cf32014bf7a0ff0b1e42f94ecc5fe9`, MIT. This is an
  independently authored port, not code released by the paper's authors.
- Use CLI target `--target-faces 1932`, `--primitive-grouping none`, and the
  implementation's defaults for local virtual-edge radius, vertex welding,
  and normal recomputation. Do not transfer textures. No parameter sweep or
  image-guided tuning is allowed in this screen.
- Frozen exact-face controls are read from
  `out/appearance-ratio-feasibility-20261124/BarramundiFish/exports/` and are
  hash-bound by [`stmw_community_port_barramundifish_manifest_20261127.json`](stmw_community_port_barramundifish_manifest_20261127.json),
  which includes the additional `stmw_port.obj` SHA-256. The full source OBJ is
  the reference; do not substitute a DAG cut. The topology check is recorded
  in [`stmw_community_port_barramundifish_preflight_20261127.json`](stmw_community_port_barramundifish_preflight_20261127.json).

## Image scoring

Use the existing `tools/mmtrain/bench_appearance_controls.py` renderer and
scorer with one additional `stmw_port` arm. The camera schedule is unchanged:
12 fixed perspective directions at distances 3.3 and 5.2. Render at 640x360
on the Iris Xe/D3D12 adapter. The reference is the 3,864-face source rendered
at 2x resolution with 4x MSAA and linearly box-resolved. Score every 1,932-face
arm with native sampling and 4x MSAA under the identical neutral grayscale
shader and camera.

Report per-view and pooled PSNR, SSIM, LDR-FLIP, silhouette XOR, and sampled
surface/normal diagnostics. The 24 views are correlated views of one reused
asset; summarize them descriptively and do not compute asset-level uncertainty
or claim generalization. The output is not a frame-time, streaming, mobile, or
human-preference result. The initial port run took 0.768 seconds; a
hash-verified replay took 0.745 seconds. These are single-run feasibility
observations, not a matched runtime-cost comparison. The replay counts and
hashes are in the [CLI receipt](stmw_community_port_barramundifish_cli_receipt_20261127.json).

## Decision rule and limits

The screen is eligible only when face count is exactly 1,932 and the existing
ManyMesh topology/boundary audit passes. A valid candidate supplies a
descriptive recent-baseline result only. Beating a control on this one reused
asset would trigger a separately frozen multi-asset development study; it
would not advance the unscored confirmation pool. Losing to meshoptimizer on
this asset does not establish that Liu et al.'s method loses generally. The
current source cohort was selected by topology and exact-boundary eligibility,
and the paper's main distinction concerns challenging non-manifold,
multi-component, and textured inputs.

The port type-checks in both Windows and WSL. Its full 458-test suite ran in
the D-drive WSL with 457 passing and one failure in the unrelated texture
worker progress assertion (`batchId === -1`); that failure does not validate
the port against the paper. Its Windows test runner was previously stopped at
startup by `spawn EPERM`. No ManyMesh source, file format, or production API is
changed by this screen.

The result is reported in
[`STMW_COMMUNITY_PORT_BARRAMUNDIFISH_20261127.md`](STMW_COMMUNITY_PORT_BARRAMUNDIFISH_20261127.md)
with the full per-view [raw receipt](stmw_community_port_barramundifish_raw_20261127.json).

## Reproduction commands

The source OBJ-to-GLB adapter and the GLB-to-OBJ export are
[`obj_to_geometry_glb.py`](obj_to_geometry_glb.py) and
[`geometry_glb_to_obj.py`](geometry_glb_to_obj.py). The tracked frozen input
manifest and preflight receipt bind every compared OBJ hash. From the Windows
repository root, reproduce the source adapter:

```powershell
python tools/mmtrain/obj_to_geometry_glb.py `
  out/appearance-asset-intake-20261124/BarramundiFish/geometry.obj `
  out/research-baselines/BarramundiFish-source.glb
```

In WSL, clone the pinned port and reproduce the simplified GLB:

```sh
git clone https://github.com/illusioneering/textured-mesh-simplification \
  /root/stmw-audit
git -C /root/stmw-audit checkout 3b9195cb75cf32014bf7a0ff0b1e42f94ecc5fe9
cd /root/stmw-audit
npm ci --ignore-scripts
npm run simplify -- --input /mnt/e/ManyMesh/out/research-baselines/BarramundiFish-source.glb \
  --output /root/stmw-audit/BarramundiFish-1932-repro.glb \
  --target-faces 1932 --primitive-grouping none
```

Back in the Windows repository root, export the geometry-only OBJ:

```powershell
python tools/mmtrain/geometry_glb_to_obj.py `
  out/research-baselines/BarramundiFish-1932.glb `
  out/research-baselines/stmw-barramundi-inputs/stmw_port.obj
```

The exact replay output hash is recorded in the CLI receipt. The Windows
D3D12 comparison used `bench_appearance_controls.py` with
`--extra-arm stmw_port --defer-flip`; its 264 lossless grayscale image arrays
are retained locally under `out/research-baselines/stmw-barramundi-frames/`
and individually hash-bound by the raw result. To calculate the identical
FLIP metric from them in WSL:

```powershell
& 'out/msaa-quality-venv/Scripts/python.exe' tools/mmtrain/bench_appearance_controls.py `
  --manifest tools/mmtrain/stmw_community_port_barramundifish_manifest_20261127.json `
  --asset BarramundiFish `
  --geometry-dir out/research-baselines/stmw-barramundi-inputs `
  --adapter 'Intel(R) Iris(R) Xe Graphics' --backend D3D12 `
  --extra-arm stmw_port --defer-flip `
  --image-dir out/research-baselines/stmw-barramundi-frames `
  --out out/research-baselines/stmw-barramundi-quality.json
```

Then run the post-process in WSL:

```sh
wsl.exe -d ManyMesh-Ubuntu-D --exec /root/manymesh-metrics/bin/python \
  /mnt/e/ManyMesh/tools/mmtrain/score_saved_appearance_flip.py \
  --report /mnt/e/ManyMesh/out/research-baselines/stmw-barramundi-quality.json \
  --image-dir /mnt/e/ManyMesh/out/research-baselines/stmw-barramundi-frames
```

## Execution accommodation

The frozen comparison conditions did not change. Windows Smart App Control
blocked the `flip_evaluator.nbflip` native extension before the first metric
was produced. The D3D12 render pass therefore saved the exact uint8 sRGB
frames as lossless NumPy arrays; `flip-evaluator` 1.7 computed LDR-FLIP from
those arrays in the authorized D-drive WSL environment. It uses the same
`inputsRGB=True`, `applyMagma=False`, and `ppd=67` call as
`bench_bevy_smaa.score`. PSNR, SSIM, silhouette XOR, and sampled surface
metrics remained on the Windows scorer. Frame hashes and the post-processing
script hash are recorded in the raw result. No Windows protection setting was
changed.

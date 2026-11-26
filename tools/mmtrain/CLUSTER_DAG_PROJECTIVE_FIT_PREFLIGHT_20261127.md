# Cluster DAG projective-fit preflight

Status: **closed for this single-cut CPU fitting configuration**. The
cluster-boundary-locked fit improved the raw ManyMesh cut, but an exact-face
meshoptimizer cut fitted by the same CPU optimizer was better on the held-out
views. This is one reused train asset and does not establish generalization or
a SIGGRAPH contribution.

## Result

All five arms use 5,290 faces and the original 10,580-face source OBJ as the
rendering reference. The screen used 16 training view/scale pairs and 24
reserved view/scale pairs from this same asset. Results are paired by view;
the views are correlated and are not independent asset samples.

| Geometry | PSNR (dB) ↑ | SSIM ↑ | Mean LDR-FLIP ↓ |
|---|---:|---:|---:|
| ManyMesh raw | 39.3176 | 0.995883 | 0.006564 |
| ManyMesh, cluster boundaries locked | 41.3902 | 0.996862 | 0.005035 |
| ManyMesh, open boundaries only locked | 39.9875 | 0.996211 | 0.006102 |
| meshoptimizer raw | 42.4441 | 0.997923 | 0.005245 |
| meshoptimizer, open boundaries only locked | **43.0076** | **0.998020** | **0.004710** |

Cluster locking helped its own ManyMesh initializer: compared with raw ManyMesh,
PSNR rose by 2.073 dB and mean FLIP fell by 0.001528. Compared with fitted
meshoptimizer, however, cluster-locked ManyMesh was 1.617 dB lower in PSNR,
0.001158 lower in SSIM, and 0.000326 worse in mean FLIP. It therefore fails the
frozen advancement gate despite its small FLIP advantage over raw
meshoptimizer. The tested configuration is closed; this does not reject
jointly fitting every hierarchy level or other training objectives.

### Geometry and costs

- The 5,290-face cut contains 29 selected DAG nodes and 2,645 vertices. The
  reconstruction matched all MMLG node faces one-to-one with the exported PLY.
- The shared cluster-boundary mask locked 1,109 vertices, unchanged bit-for-bit
  after fitting. All arms retained 5,290 faces, had zero open boundary edges,
  and passed the recorded topology audit. Maximum cluster-fit displacement was
  0.004076 normalized units against a 0.012 cap. The minimum face-normal dot
  ratio was 0.200089 against the 0.20 floor. Geometric self-intersections were
  not tested.
- CPU fit wall times were 5.639 s for cluster-locked ManyMesh, 3.020 s for the
  unconstrained ManyMesh ablation, and 5.410 s for fitted meshoptimizer. These
  are two-thread Mitsuba optimization times on the local CPU, not render frame
  times. Process peak RSS was 318,054,400 bytes.
- With only float32 XYZ positions and uint32 triangle indices, each exact-face
  geometry buffer is 95,220 bytes (2,645 vertices and 5,290 faces) for both
  ManyMesh and meshoptimizer. This omits normals, UVs, materials, and container
  headers; it is not an `.mmb`, compressed, or network payload measurement. The
  experiment's compressed NPZ archive is 337,214 bytes because it stores the
  source, all control geometries, all fits, cluster labels, and lock mask.
- Sampled symmetric surface Chamfer L1 was 0.007615 for cluster-locked
  ManyMesh and 0.007625 for fitted meshoptimizer; mean absolute normal
  agreement was 0.941872 and 0.941615 respectively. These 20,000-sample
  single-asset estimates are descriptive and do not overturn the image-quality
  gate.

## Source-reference and cluster-label audit

The scoring reference is the original derived OBJ, SHA-256
`b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`. The
full-detail PLY is used only to map MMLG source vertex IDs; it is not used as
the scoring reference. A nearest-vertex bijection maps its 5,290 positions to
the OBJ with maximum coordinate difference `4.2312e-6`; after mapping, all
10,580 unoriented source face-index triples match exactly. This validates the
mapping aid against the source before using it to restore cluster labels.

The PLY itself has no DAG node property. The fit script reads MMLG v7, maps its
29 selected node face lists to the candidate PLY by exact float32 position
triples, and rejects the run unless all faces map one-to-one. The source OBJ's
text vertex order is not assumed to match mmgeo's internal vertex order.

An earlier diagnostic invocation scored against the full-detail PLY. It was
excluded and retained only under the ignored output directory; it is not part
of this report or the raw receipt below. All reported scores use the original
source OBJ directly.

## Protocol and limits

The fit used Mitsuba 3.9.0, Dr.Jit 1.4.0 `llvm_ad_rgb`, two CPU threads,
`direct_projective`, 96 x 96 neutral-material renders, 4 spp for fitting, and
the existing fixed Laplacian preconditioner. Optimization used at most eight
iterations over 16 fixed training views, with a 0.002 maximum step and a
0.012 displacement cap. Scoring used 24 different directions/scales at 16
spp. The reference, light, seed, transfer function, and camera were identical
across each paired score.

This screen did not measure hardware MSAA, SMAA, an upscaler, temporal quality,
mobile performance, GPU time, or user preference. It did not evaluate an
asset-held-out model or every level of the DAG. It used same-face
meshoptimizer as its strongest recorded control but did not include a QEM arm;
it must not be presented as a full comparison against all geometry baselines.

The run used D-drive WSL2 Ubuntu 26.04 on the Intel Core i7-13700H, CPython
3.12.3, Linux kernel `6.18.58.1-microsoft-standard-WSL2`, and the package
versions recorded in the raw receipt. The fit script SHA-256 is
`4b5015e10dc2ff63fdd3351f76b399b60d3511b3c29f827a6760a4fa67c9d018`; the
shared fit implementation SHA-256 is
`85c6d539c68ca08a98cf31284dfd7f1db8eefcd74856bd07606784e46513eef1`.
The exact local invocation was:

```sh
PATH="/mnt/e/ManyMesh/out/stream-rate-distortion-preflight-20261127/84736/bin:$PATH" \
/root/ManyMesh-build/projective-rgb-venv/bin/python \
  /mnt/e/ManyMesh/tools/mmtrain/fit_cluster_dag_projective_cpu.py \
  --source-obj /mnt/e/ManyMesh/out/stream-rate-distortion-preflight-20261127/84736/source.obj \
  --source-sha256 b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c \
  --candidate-dir /mnt/e/ManyMesh/out/cluster-fit-preflight-matched-20261127/84736 \
  --out /mnt/e/ManyMesh/out/cluster-fit-preflight-matched-20261127/84736/result-source-reference.json
```

The final result was independently audited from the raw receipt and
geometry archive: per-view PSNR/SSIM/FLIP means, source/script/geometry hashes,
exact face budgets, topology and source-boundary eligibility, locked vertices,
displacement, and normal orientation all passed the verifier. The local
geometry archive is not committed; its SHA-256 is
`400c3ad3270d88aade89ba9d2da9ad0f01232aabdc11c19ec686c57b6821fb15` and it
remains under `out/cluster-fit-preflight-matched-20261127/84736/`.

See the [frozen protocol](CLUSTER_DAG_PROJECTIVE_FIT_PREFLIGHT_PROTOCOL_20261127.md),
[full per-view receipt](CLUSTER_DAG_PROJECTIVE_FIT_PREFLIGHT_20261127.json), and
[independent verifier](verify_cluster_dag_projective_cpu.py). The next method
decision requires a new, pre-registered change that can challenge the fitted
meshoptimizer baseline before any confirmation-pool scoring.

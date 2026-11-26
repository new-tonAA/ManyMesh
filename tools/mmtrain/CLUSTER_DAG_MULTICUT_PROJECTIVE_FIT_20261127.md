# Shared-position multi-cut cluster-DAG fit

Status: **closed for this one-asset, three-cut CPU configuration**. The joint
fit improved the raw ManyMesh images at the 2,286- and 5,290-face budgets, but
lost to the strongest eligible fitted control at every budget. The result does
not establish generalization, a SIGGRAPH contribution, final reconstruction
quality, or mobile performance.

## Results

Every cut was scored against the original 10,580-face OBJ at the same 24
reserved direction/scale pairs. Lower LDR-FLIP is better; higher PSNR and SSIM
are better. The 2,286-face meshoptimizer control and 5,290-face meshoptimizer
control passed topology checks. The 7,934-face meshoptimizer output contained
duplicate geometric triangles, so it was excluded before scoring; the
predeclared exact-face QEM fallback passed and was used at that budget.

| Requested retention | Actual faces / nodes | Eligible control | Joint ManyMesh PSNR / SSIM / FLIP | Fitted control PSNR / SSIM / FLIP | Joint minus fitted control: PSNR / SSIM / FLIP |
|---:|---:|---|---|---|---|
| 25% (actual 21.61%) | 2,286 / 1 | meshoptimizer | 38.4597 / 0.993856 / 0.007970 | 39.3481 / 0.995655 / 0.007432 | -0.8884 dB / -0.001798 / +0.000538 |
| 50% | 5,290 / 29 | meshoptimizer | 41.2446 / 0.996802 / 0.005478 | 43.0076 / 0.998020 / 0.004710 | -1.7629 dB / -0.001217 / +0.000768 |
| 75% (actual 74.99%) | 7,934 / 83 | QEM | 47.4264 / 0.999129 / 0.002712 | 54.9397 / 0.999748 / 0.001018 | -7.5132 dB / -0.000619 / +0.001694 |

The joint fit improved raw ManyMesh at 2,286 faces by 1.1863 dB and reduced
mean LDR-FLIP by 0.001588. At 5,290 faces it improved raw ManyMesh by 1.9270
dB and reduced FLIP by 0.001086. At 7,934 faces it regressed against its own
raw cut by 1.2338 dB and increased FLIP by 0.000725. These gains over the
initializer did not survive comparison with the fitted controls, so the frozen
gate failed at all three budgets.

The equal-face raw/fitted control scores were:

| Faces | Raw control PSNR / SSIM / FLIP | Fitted control PSNR / SSIM / FLIP |
|---:|---|---|
| 2,286 meshoptimizer | 39.0122 / 0.995442 / 0.008234 | 39.3481 / 0.995655 / 0.007432 |
| 5,290 meshoptimizer | 42.4441 / 0.997923 / 0.005245 | 43.0076 / 0.998020 / 0.004710 |
| 7,934 QEM | 55.5041 / 0.999761 / 0.001072 | 54.9397 / 0.999748 / 0.001018 |

All ManyMesh, fitted-candidate and eligible-control meshes retained their exact
face budgets, had zero open boundary edges, preserved the source boundary,
and passed the topology audit. The 1,697 globally locked MMLG vertices were
unchanged. Maximum displacement was 0.004974 normalized units against the
0.012 cap. Minimum face-normal dot ratios were 0.465849, 0.263985 and 0.263985
at the three cuts, all above the 0.20 floor. Self-intersections were not
tested.

## Protocol and cost

The source is Thingi10K file 84736 (Thingiverse item 28675, `fat.stl`),
Creative Commons Attribution, train split. STL SHA-256 is
`4de846fb7c6ae5259655d89f2cf9c8ef021c234da02efd81df47efa0744a0da4`; the
derived source OBJ SHA-256 is
`b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`. The
source file is available from the
[Thingiverse asset URL](https://thingiverse-production-new.s3.amazonaws.com/assets/43/dd/83/cf/7b/fat.stl)
or the [pinned Thingi10K mirror](https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/1e52df627995ba43b7b91143af4bed86f570037a/raw_meshes/84736.stl).

The same MMLG v7 binary was used for all cuts (SHA-256
`0412224b9846cadc5a25186a2e010fecea7d652de25f6c5891bc307c07ea51ed`). It has
246 nodes and nine levels. The 3,985 MMLG vertices in the union of the three
selected cuts were optimized as one shared position field. Training averaged
16 view/scale losses at 96 x 96 and 4 spp across all three cuts. Scoring used
24 reserved view/scale pairs at 96 x 96 and 16 spp. The per-cut meshes used
the original source OBJ as the image reference. This offline sample-based
filtering is an AA proxy; it is not hardware MSAA, SMAA, temporal accumulation,
or an upscaler. The 24 views are correlated views of one reused training
asset, not 24 independent samples.

| Faces | Position + index bytes for candidate and control |
|---:|---:|
| 2,286 | 41,148 bytes each |
| 5,290 | 95,220 bytes each |
| 7,934 | 142,812 bytes each |

These counts include float32 XYZ positions and uint32 triangle indices only;
they exclude normals, UVs, materials, compression and container headers. The
local compressed archive stores all cuts and controls and is 603,243 bytes.
Joint fit time was 17.84 s. The three independent control fits took 1.32 s,
5.76 s and 8.51 s (15.59 s total); simplification time is recorded separately
in the raw receipt. These are CPU optimization timings, not render frame times.
Process peak RSS was 345,894,912 bytes. The run used the D-drive WSL2 Ubuntu
environment, CPython 3.12.3, Mitsuba 3.9.0, Dr.Jit 1.4.0, NumPy 2.3.4, SciPy
1.15.3, scikit-image 0.25.2 and flip-evaluator 1.7. The host's Intel Core
i7-13700H identification is recorded in the
[workstation verification report](LOCAL_WORKSTATION_VERIFICATION_20261126.md).

## Decision and limits

Close this shared-position, three-cut configuration. The larger 7,934-face
gap to QEM and the FLIP regressions at all three cuts make additional tuning on
this asset unjustified. This is not evidence against every way to optimize a
cluster hierarchy: it tests one neutral-material CPU objective, one asset and
three selected cuts, with no QEM comparator at the first two budgets. It does
not fit every DAG cut or transition, use actual final MSAA/upscaling, test
asset-held-out generalization, or measure mobile performance or user
preference. The 30-model confirmation pool remains unscored.

The exact fit command, package versions, cut/node hashes, all per-view PSNR,
SSIM and LDR-FLIP rows, surface samples, optimizer traces, geometry-buffer
accounting and decision are in the
[raw receipt](CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_20261127.json). The frozen
[protocol](CLUSTER_DAG_MULTICUT_PROJECTIVE_FIT_PROTOCOL_20261127.md),
[fitter](fit_cluster_dag_multicut_projective_cpu.py) and
[independent verifier](verify_cluster_dag_multicut_projective_cpu.py) are
checked in. The geometry archive remains local at
`out/cluster-dag-multicut-fit-20261127/result.geometry.npz`, SHA-256
`3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe`.

The ratio cuts were generated with the existing WSL binary and the following
fixed options (repeat the command for each `ratio` and matching output path):

```sh
mmgeo source.obj --out out/cluster-dag-multicut-fit-20261127/<ratio> \
  --mode dag --ratio 0.7 --target-ratio <ratio> --target-ratio-cut <ratio> \
  --cluster-verts 128 --cluster-tris 128 --dag-group 8 \
  --attribute-qem 1 --corner-seam 1 --corner-split-uv 1 \
  --write-dag 1 --dump-format ply
```

For label reconstruction, put the byte-identical full-detail mapping files
(`full/selected.ply` and `full/lod_graph.json`) under each ratio directory.
They were generated from the same MMLG binary; the verifier checks the graph
and mesh hashes. The meshoptimizer Node helper needs the existing WSL Node
bridge on `PATH`, as recorded in the raw receipt. The binary was built from ManyMesh source revision
`21cef5a92739edd6d1d751417a2c20efe4ec2a2d`; its SHA-256 is recorded in the
receipt. Source OBJ preparation is documented in the
[stream pilot protocol](STREAM_RATE_DISTORTION_PILOT_PROTOCOL_20261127.md).
No packages were installed and no Windows security settings changed.

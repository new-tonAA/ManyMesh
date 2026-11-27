# Third-party STMW port: BarramundiFish geometry screen

Status: **the tested one-asset geometry-only port screen failed its quality
gate.** This is neither a reproduction nor a rejection of Liu et al.'s method.

## Frozen comparison

The experiment used Khronos BarramundiFish geometry (CC0), 3,864 source faces,
and four eligible 1,932-face outputs: ManyMesh, border-preserving QEM,
meshoptimizer with locked border, and the MIT community TypeScript port of
*Simplifying Textured Triangle Meshes in the Wild*. The port is pinned at
`3b9195cb75cf32014bf7a0ff0b1e42f94ecc5fe9`; it is not released by the paper's
authors. Its CLI used the default local virtual-edge radius, vertex welding,
and normal recomputation, with primitive grouping disabled and no texture
transfer. All compared meshes have exactly 1,932 faces. The port result has no
topology error, zero boundary edges, and preserves the source boundary.

The full source mesh is the reference. It was rendered at 1280x720 with 4x
MSAA and linearly box-resolved to 640x360. Each candidate was rendered at
640x360 with native sampling and 4x MSAA on the laptop's Intel Iris Xe using
D3D12 (driver 31.0.101.4502). The fixed camera set is 12 directions at
distances 3.3 and 5.2, for 24 views, under the same neutral grayscale shader.
PSNR uses pooled mean squared error across pixels/views; SSIM, LDR-FLIP and
silhouette XOR are arithmetic means over the 24 views. LDR-FLIP 1.7 used the
same `ppd=67`, `inputsRGB=True`, `applyMagma=False` settings as the existing
scorer, computed from lossless D3D12 frame arrays in the D-drive WSL distro.
The Windows metric stack was NumPy 2.3.4, SciPy 1.15.3, and scikit-image
0.25.2; the WSL FLIP post-process used NumPy 2.5.5. The final Windows run had
no SciPy/NumPy compatibility warning.

These 24 views are correlated observations of one reused development asset.
They do not provide asset-level uncertainty, generalization, a preference
study, or frame-time evidence. The geometry-only source and lack of texture
transfer also omit the paper's central textured-mesh setting.

## Rendered quality

The image metrics compare each 1,932-face output to the full source reference.
Lower FLIP and silhouette XOR are better; higher PSNR and SSIM are better.

| Method | Native PSNR (dB) | Native SSIM | Native FLIP | Native silhouette XOR | 4x MSAA PSNR (dB) | 4x MSAA SSIM | 4x MSAA FLIP | 4x MSAA silhouette XOR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ManyMesh | 34.495 | 0.99110 | 0.003627 | 0.001628 | 36.861 | 0.99415 | 0.003267 | 0.000886 |
| Border QEM | 37.782 | 0.99416 | 0.002489 | 0.001170 | 43.861 | 0.99721 | 0.002003 | 0.000351 |
| meshoptimizer | 37.729 | 0.99492 | 0.002225 | 0.001215 | 44.351 | 0.99806 | 0.001676 | 0.000377 |
| STMW community port | 18.417 | 0.94922 | 0.039454 | 0.037127 | 18.442 | 0.94938 | 0.039456 | 0.036894 |

Against meshoptimizer, the port is lower by **19.312 dB PSNR** and higher by
**0.037229 FLIP** without MSAA. With 4x MSAA, it is lower by **25.908 dB** and
higher by **0.037780 FLIP**. MSAA does not materially change the port result.
This is a clear loss for this input and implementation configuration, not a
small perceptual tradeoff.

## Geometry diagnostics

The table reports deterministic area-uniform 20,000-point samples in each
direction. These are nearest-point-cloud estimates, not exact point-to-triangle
distances. Normal agreement uses the absolute dot product.

| Method | Symmetric Chamfer L1 | Bidirectional distance p95 | Normal agreement |
|---|---:|---:|---:|
| ManyMesh | 0.005929 | 0.011154 | 0.97743 |
| Border QEM | 0.005507 | 0.010622 | 0.98251 |
| meshoptimizer | 0.005433 | 0.010574 | 0.98374 |
| STMW community port | 0.172137 | 0.546329 | 0.68399 |

The geometric-distance diagnostics agree with the rendered-quality ranking.

## Decision and limits

Do not advance this geometry-only third-party port to a larger study on the
strength of this result. It is far outside the tested quality frontier against
both conventional controls. This does not test texture transfer, challenging
non-manifold inputs, triangle soups, or the author's implementation, and so it
does not close the published method as a baseline for those claims. A faithful
implementation or author code would need a newly frozen, texture-aware study.

The community port type-checks, but its WSL suite has 457/458 passing; the one
failure is a texture-worker progress assertion (`batchId === -1`), not a mesh
simplification test. The earlier Windows test runner failed at startup with
`spawn EPERM`. Neither result validates fidelity to the paper.

The image-quality scorer and FLIP post-processor hashes, 264 saved-frame hashes,
per-view raw data, adapter, and package versions are in the [machine-readable
receipt](stmw_community_port_barramundifish_raw_20261127.json). The frozen
inputs and eligibility audit are the [manifest](stmw_community_port_barramundifish_manifest_20261127.json)
and [preflight receipt](stmw_community_port_barramundifish_preflight_20261127.json).
The complete conditions and execution accommodation are in the
[protocol](STMW_COMMUNITY_PORT_BARRAMUNDIFISH_PROTOCOL_20261127.md), including
the [hash-verified CLI replay](stmw_community_port_barramundifish_cli_receipt_20261127.json).

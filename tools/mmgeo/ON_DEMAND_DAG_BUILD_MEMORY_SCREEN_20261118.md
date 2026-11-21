# On-demand DAG construction under a memory cap (2026-11-18)

## Scope

This is a raster-only ManyMesh research screen. It excludes ray tracing, ReSTIR, and path
reservoirs. It does not claim that out-of-core mesh simplification or on-demand LOD is new.

## Source-level finding

The current file-backed `StreamingLodGraph` keeps a graph header and node offsets, then reads
serialized nodes/pages on demand. Its byte-budgeted cache bounds resident pages during use. It
does not build or extend the hierarchy.

`buildLodGraph` follows a different, fully resident path. It copies the source into `graphMesh`,
keeps leaf and generated-node index arrays in `graph`, and materializes a `std::vector<ClusterLods>`
containing the per-cluster simplification results before appending those results to the graph. It
then constructs grouped parents level by level. `LodGraphBuildStats` records phase times, attempts,
and generated-vertex counts, but does not report peak RSS or peak temporary bytes. These source
facts suggest overlapping retained representations can raise the build high-water mark; their
actual memory cost has not been measured in this screen.

Relevant code: `libs/manymesh/src/LodGraph.cpp` (`buildLodGraph`, especially the `graphMesh` copy,
`clusterLods`, and per-level group build); `libs/manymesh/include/manymesh/Streaming.h`
(`StreamingLodGraph`, `LodStreamingCache`); `libs/manymesh/include/manymesh/LodGraph.h`
(`LodGraphBuildStats`).

## Prior-art boundary

The broad direction is occupied. Out-of-core mesh processing includes streaming simplification and
remeshing; Lindstrom and Silva describe large-mesh simplification using external-memory sorting,
and Ahn et al. describe out-of-core remeshing with synchronized mesh and mapping streams. The
`End-to-End Compressed Meshlet Rendering` work treats selective streaming of independently
compressed meshlets. Therefore none of these phrases is a contribution by itself: "out-of-core
simplification," "streaming mesh LOD," "bounded-memory mesh processing," or "on-demand hierarchy
access."

- [Large Mesh Simplification using Processing Sequences](https://www.labri.fr/perso/preuter/imageSynthesis/03-04/papers/large.pdf)
- [Out-of-Core Remeshing of Large Polygonal Meshes](https://cg.postech.ac.kr/papers/vis2006.pdf)
- [End-to-End Compressed Meshlet Rendering](https://diglib.eg.org/bitstream/handle/10.1111/cgf15002/v43i1_12_cgf15002.pdf)
- [Clustered HLOD with progressively simplified boundaries (2026)](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380)

The narrower, still-unproven question is whether ManyMesh can emit a *partially usable strict-gate
DAG* under a hard working-set cap by committing independently valid parents to a disk-backed graph,
releasing their temporary simplification state, and continuing later, while preserving the same
complete-cut quality frontier at a matched construction-work budget. The research distinction, if
any, would have to be an algorithm and measured frontier for incremental construction under
ManyMesh's exact topology, attribute, boundary, and geometry gates. The existing streaming reader
only supplies the storage/access substrate.

## Falsifiable experiment

Before changing production code, make a low-memory source and data audit, then run a small controlled
prototype only when the machine has safe memory headroom:

1. Add process peak-RSS measurement to the experiment harness (not the renderer) and record a
   baseline build's phase, output size, and full working-set peak.
2. Compare full-resident construction with incremental parent batches that can be serialized and
   evicted after each batch. Every committed output must still pass the existing strict gates and
   the graph must always expose a valid cut covering the input exactly once.
3. Match output triangle budgets and accumulated-error limits. Evaluate complete cuts with the
   conventional raster metric, and report time-to-first-usable-cut, final build time, peak RSS,
   temporary disk bytes, resident graph bytes, and cut quality.
4. Include spatial-median retry, the current full build, and a disk-backed version of the same
   policy. Use held-out assets and camera paths. Keep memory below an explicit machine budget rather
   than relying on average usage.

Kill this direction if the memory reduction comes only from moving the same total cost to excessive
disk traffic, if no useful cut is available earlier, if complete-cut quality degrades at matched
work, or if a standard out-of-core baseline reaches the same frontier at lower total cost. No
implementation, benchmark, or SIGGRAPH contribution is established by this source audit.

## Current resource constraint

At the time of this screen, the host reported 2.18 GiB available RAM out of 15.73 GiB. No build,
renderer, or large asset run was started. Defer runtime profiling until available memory is safely
higher; this note records architecture and a testable question only.

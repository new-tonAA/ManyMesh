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

The broad direction is occupied. Birkholz's WSCG 2006 paper, [Out of Core continuous LoD-Hierarchies
for Large Triangle Meshes](https://naos-be.zcu.cz/server/api/core/bitstreams/94d6a8d2-e8cd-4b13-b02a-61d7ac14dab2/content),
builds an external-memory edge-collapse hierarchy with a user-adjustable memory footprint. It
states that the result is the same hierarchy as an in-core method and describes view-dependent
reconstruction that stops at a time or memory limit. This directly occupies generic bounded-memory
hierarchy construction and capped-cost LOD access. Lindstrom and Silva describe large-mesh
simplification using external-memory sorting, and Ahn et al. describe out-of-core remeshing with
synchronized mesh and mapping streams. `End-to-End Compressed Meshlet Rendering` treats selective
streaming of independently compressed meshlets. Therefore none of these phrases is a contribution
by itself: "out-of-core simplification," "streaming mesh LOD," "bounded-memory mesh processing," or
"on-demand hierarchy access."

- [Large Mesh Simplification using Processing Sequences](https://www.labri.fr/perso/preuter/imageSynthesis/03-04/papers/large.pdf)
- [Out-of-Core Remeshing of Large Polygonal Meshes](https://cg.postech.ac.kr/papers/vis2006.pdf)
- [End-to-End Compressed Meshlet Rendering](https://diglib.eg.org/bitstream/handle/10.1111/cgf15002/v43i1_12_cgf15002.pdf)
- [Clustered HLOD with progressively simplified boundaries (2026)](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380)

An additional primary-source check found a close runtime neighbor: Derzapf, Menzel, and Guthe,
[Parallel View-Dependent Out-of-Core Progressive Meshes (VMV 2010)](https://doi.org/10.2312/PE/VMV/VMV10/025-032).
Their paper describes a spatial hierarchy and a compact progressive-mesh representation for
out-of-core rendering. Its runtime stores operations and attributes in file-backed nodes, loads
required nodes on demand, and caps node transfers per frame. It does not describe ManyMesh's
offline builder or its topology/attribute gates, but it occupies partial residency, progressively
usable geometry, view-dependent updates, and bounded transfer as broad novelty claims. Birkholz
(2006) remains the closer baseline for bounded-memory hierarchy construction itself. Any remaining
distinction must measure strict validation, build peak RSS, time-to-first complete cut, and total
disk/build cost against both construction and runtime-streaming systems.

The only remaining question here is a narrowly scoped engineering comparison: can the existing
builder emit a *partially usable strict-gate DAG* under a hard working-set cap by committing valid
parents to disk, releasing temporary state, and continuing later, while preserving the complete-cut
quality frontier at matched construction work? This is not a novelty claim. Any future paper would
need to show a concrete distinction from Birkholz's capped external-memory hierarchy and other
out-of-core methods, then demonstrate a reproducible advantage under ManyMesh's topology,
attribute, boundary, and geometry gates. The current streaming reader supplies storage/access only;
it does not establish that distinction.

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
4. Include spatial-median retry, the current full build, a faithful bounded-memory collapse baseline
   based on established out-of-core methods, and a disk-backed version of the same policy. Use
   held-out assets and camera paths. Keep memory below an explicit machine budget rather than
   relying on average usage.

Stop this direction if the memory reduction only moves cost to excessive disk traffic, no useful cut
is available earlier, complete-cut quality degrades at matched work, or a faithful out-of-core
baseline reaches the same frontier at lower total cost. No implementation, benchmark, or SIGGRAPH
contribution is established by this source audit.

## Current resource constraint

At the time of this screen, the host reported 2.18 GiB available RAM out of 15.73 GiB. No build,
renderer, or large asset run was started. Defer runtime profiling until available memory is safely
higher; this note records architecture and a testable question only.

## Follow-up execution check (2026-11-22)

The host reported 3.41 GiB available RAM out of 15.73 GiB. The cached
`out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe` predates the current
`Simplifier.h`, so it is stale for source-level measurements. `msbuild.exe` and `cl.exe`
were not discoverable in `PATH` or the checked Visual Studio 2022/2019 locations. No build or
benchmark was run, and no runtime claim follows from this check. Resume only with a current
buildable target and sufficient memory headroom.

# mmgpu

`mmgpu` is a standalone Vulkan 1.0 prototype for the runtime pieces that Filament's public
`RenderableManager` API does not expose:

- DAG cut selection in a compute shader (`vkCmdDispatch`).
- GPU-side index compaction and indirect-command generation in the same dispatch.
- Three-pass GPU vertex compaction (mark referenced vertices, assign dense ids and gather
  positions, rewrite indices) with no cross-invocation spin loop.
- Real indexed indirect draws (`vkCmdDrawIndexedIndirect`) consuming the GPU-produced buffers.
- A depth-tested visibility buffer with cluster ID, triangle ID and depth attachments.

It deliberately does not link `vulkan-1.lib`; `VulkanApi` loads the system loader dynamically on
Windows. This keeps the rest of the repository buildable on machines without the Vulkan SDK.

## Build

The target is only added on Windows host builds:

```bat
cmake --build out\cmake-release --target mmgpu
```

## Run

```bat
out\cmake-release\tools\mmgpu\mmgpu.exe assets\models\torus\torus.obj ^
    --width 640 --height 360 --threshold-px 2 --out out\mmgpu-torus
```

Useful options:

```text
--list-devices
--device N
--eye X,Y,Z
--target X,Y,Z
--fov-deg F
--near F
--far F
--threshold-px F
--levels N
--clusters N
--ratio F
--corner-seam 0|1
--corner-split-uv 0|1
--legacy-submit
```

`--corner-seam` (default 1) enables the corner-aware seam simplifier, and
`--corner-split-uv` (default 1) keeps divergent UV clusters as separate vertices at the same
position. Generated vertices are uploaded after the source range, so GPU compaction, indirect
draw and the CPU visibility reference all index the same source+generated vertex space.

The tool prints CPU/GPU cut agreement, compacted index/vertex counts, indirect draw count,
visibility-buffer coverage, node and triangle agreement, and depth mismatch. It writes CPU, GPU
and diff PGM images to the output directory. On torus at 640x360 with a 2 px threshold the
corner-seam path produces 9 draws / 908 triangles and compacts 515 of the 978 uploaded vertices
(174 source + 341 generated). The dense vertex ids are assigned in parallel, so the tool reports
both the raw id order and the permutation-independent contract: the compacted vertex set and
the triangle topology compared by exact positions, not by dense id.

Four-model validation of the corner-seam path (320x180, 2 px threshold, two frames):

| model | cut triangles | compacted vertices | visibility overlap | depth mismatch |
| --- | ---: | ---: | ---: | ---: |
| torus | 712 | 414 (73 source + 341 generated) | 99.98% | 0 |
| monkey | 8,360 | 5,630 (5,006 source + 624 generated) | 100.00% | 0 |
| sphere | 4,976 | 2,651 (2,540 source + 111 generated) | 100.00% | 0 |
| cloth | 26,574 | 13,739 (12,564 source + 1,175 generated) | 99.99% | 0 |

In all four models the CPU/GPU node set, selected triangle count, compacted vertex set and
compacted triangle topology match; the one-pixel coverage differences are rasterization
rounding at a silhouette pixel, not missing geometry.

## Steady-state cost

Every pass now owns its Vulkan resources for the lifetime of the process: cut and compaction
buffers, descriptor pools and sets, the visibility attachments, the framebuffer and the three
readback buffers are created once per mesh/viewport. A frame only clears the small counters that
the shaders do not overwrite (the selected mask, the compaction counters and the indirect
commands) and refreshes the node table. The readback vectors are reused as well, so no pixel
buffer is reallocated or zeroed per frame.

Measured on Intel Iris Xe, torus, 640x360, 2 px threshold, five frames (warm average):

| quantity | value |
| --- | --- |
| host setup | 0.007 ms |
| one submit + one wait | **1.24-1.42 ms** |
| cut GPU timestamp | 0.33 ms |
| vertex compaction GPU timestamp | 0.05 ms |
| visibility draw GPU timestamp | 0.11 ms |
| validation readback (3 attachments + counters) | 23.6 ms |
| whole frame incl. validation | 25.9 ms |

The same path was re-run on monkey (640x360, 3 frames: 1.58 ms submit, cut 0.37 ms,
compaction 0.14 ms, visibility 0.17 ms) and cloth (320x180, 2 frames: 5.38 ms submit, cut
3.68 ms, compaction 0.50 ms, visibility 0.42 ms). In all four models the GPU cut matched the CPU
cut, the compacted source-vertex set and triangle topology matched, visibility overlap was
100%, and depth mismatch was zero. The dense vertex ids are a valid permutation, not a
bit-identical match, which is expected because the gather pass assigns ids in parallel.

The earlier implementation submitted cut, vertex compaction and visibility separately and called
`vkQueueWaitIdle` after each submit. With `--legacy-submit` on the same machine it measures
**2.56-3.01 ms** for the three submit+wait pairs; the single-submission path is about 2x faster.
The single-submission path records the cut dispatch, the three compaction dispatches, the
visibility render pass and the three attachment copies into one command buffer, with compute ->
compute and compute -> graphics barriers between stages. The only host readbacks are validation;
a shipping renderer drops them and keeps the visibility attachments on the GPU.

The compaction mark pass is dispatched over the full source index capacity. It reads the live
compacted index count from the cut counter block in the shader, so no stage needs a CPU round
trip. The indirect draw likewise covers the whole command capacity; unused slots stay zeroed and
produce zero-sized draws.

## RenderDoc verification

The single-submission path is captured with RenderDoc 1.46 on Intel Iris Xe
(`out/renderdoc-mmgpu/single_torus_capture.rdc` and `.xml`, 320x180, 2 px threshold). The
capture contains exactly:

| command | count |
| --- | --- |
| `vkQueueSubmit` / `vkQueueWaitIdle` | **1 / 1** |
| `vkCmdDispatch` (cut + 3 compaction passes) | 4 |
| `vkCmdDrawIndexedIndirect` | 1 |
| render pass / `vkCmdEndRenderPass` | 1 / 1 |
| `vkCmdCopyImageToBuffer` (color0/color1/depth readback) | 3 |
| `vkCmdPipelineBarrier` | 7 |

The barriers are host-write -> compute/draw, three compute -> compute, compute -> indirect/vertex
input, graphics -> transfer for the three image copies, and transfer/compute -> host for the
validation readback. `hostBarrier()` used to name `ALL_COMMANDS` and the compute hand-off used
`ALL_GRAPHICS`; both are now narrowed to the stages that actually consume the buffers.

The cut's screen-error test uses the nearest point of each node's bounding sphere
(`dot(center - eye, forward) - radius`, clamped to the near plane), the same quantity as
`GeometryError::screenSpaceErrorForSphere()` in the library. The host reference and the GLSL
`screenError()` used to subtract neither the radius nor the near clamp, which could select a
coarser cut than the CPU for large clusters close to the camera.

Headless Vulkan has no present/frame boundary, so `TriggerCapture()` alone never starts. Set
`MMGPU_RENDERDOC_MODE=start` to bracket the explicit compute frame with `StartFrameCapture()` /
`EndFrameCapture()`. If RenderDoc's Vulkan layer is not registered system-wide, point the loader
at the portable install with `VK_LAYER_PATH=<dir>`, `VK_INSTANCE_LAYERS=VK_LAYER_RENDERDOC_Capture`
and `ENABLE_VULKAN_RENDERDOC_CAPTURE=1`; this is what the capture above used.

`mmgpu` now exits with 0 when the permutation-independent contract matches. The previous exit
code still required bit-identical dense vertex ids, so a successful run reported 2 even though
the source-vertex set, triangle topology and draw commands all matched. The four-model A/B
(torus, monkey, sphere, cloth, 320x180, two frames) passes with exit 0 on both the single-submit
and `--legacy-submit` paths, with 100% visibility overlap and zero depth mismatch.

## Status

Validated on Intel Iris Xe with torus, monkey, sphere and cloth. On torus and monkey the GPU cut
matches the CPU cut exactly; visibility node agreement is 99.99% and depth mismatch is zero in
the reported test views. The remaining sub-percent triangle disagreement comes from GPU
rasterization tie-breaking at shared edges, not from a different cut. The CPU reference must be
built with `compactSourceVertices = true` to compare against the GPU's cut-local vertex buffer;
the dense id order itself is not part of the contract.

This is a real Vulkan prototype, not a Filament application integration. Filament's backend
already implements `dispatchCompute` (Vulkan, OpenGL, WebGPU and Noop) and `compute_test --api
vulkan` passes 5/5 on Intel Iris Xe, including a regression that uploads the flattened
`GpuLodNode` table and index buffer as SSBOs and checks every field from compute. What is missing
is the public application surface for persistent storage buffers, compute programs and dispatch,
plus Android GPU validation. Cut selection, index/draw compaction and vertex compaction no longer
need a CPU round trip on this path.

# mmgpu

`mmgpu` is a standalone Vulkan 1.0 prototype for the runtime pieces that Filament's public
`RenderableManager` API does not expose:

- DAG cut selection in a compute shader (`vkCmdDispatch`).
- Real indexed indirect draws (`vkCmdDrawIndexedIndirect`).
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
```

The tool prints CPU/GPU cut agreement, indirect draw count, visibility-buffer coverage, node and
triangle agreement, and depth mismatch. It writes CPU, GPU and diff PGM images to the output
directory.

## Status

Validated on Intel Iris Xe with torus, monkey, sphere and cloth. On torus and monkey the GPU cut
matches the CPU cut exactly; visibility node agreement is 99.99% and depth mismatch is zero in
the reported test views. The remaining sub-percent triangle disagreement comes from GPU
rasterization tie-breaking at shared edges, not from a different cut.

This is a real Vulkan prototype, not a Filament backend integration. Production use still needs
the same compute and indirect paths wired into Filament's Vulkan backend, persistent GPU buffers,
GPU-side culling/compaction, and Android validation.

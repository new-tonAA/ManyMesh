# Local workstation verification — 2026-11-26; rechecked 2026-11-27

This report records build and test execution on the development laptop after
Windows Smart App Control blocked the repository's unsigned test binaries.
WSL2 was used without changing Smart App Control, Defender, or their
exclusions. These are build/test results only; no image-quality, optimization,
CUDA, mobile, or performance experiment ran.

## Source and environment

- Repository base commit: `21cef5a92739edd6d1d751417a2c20efe4ec2a2d`.
- The first run used a clean checkout. The later D-drive source copy used the
  same commit with only documentation changes present in the worktree; no C++
  source changes were present.
- Environment: WSL2 Ubuntu 26.04, Clang/Clang++ 17.0.6, libc++ 17,
  CMake 4.2.3, Ninja 1.13.2. WSL kernel 6.18.58.1-1.
- The verified distro is `ManyMesh-Ubuntu-D`, registered from
  `D:\ManyMesh-WSL\ManyMesh-Ubuntu-D\ext4.vhdx`. Its SHA-256 is
  `88C8AD07369586F733D057369F3475339D6136554FD78EEE7A0F849FA47B4FEF`.
  The earlier `ManyMesh-Ubuntu` distro and its VHDX on E: were retained.
- A self-contained source copy, including `.git`, is at `/root/ManyMesh`
  inside that D-drive distro. The copy excludes the 33 GB `out/` results
  directory and restores the tracked `build/` scripts. Its Git status matched
  the Windows worktree. The fresh build directory is `/root/ManyMesh-build`.
- An earlier build directory, `/root/mm-cmake-manymesh`, still points to the
  original mounted source `/mnt/e/ManyMesh`; its results are listed separately.
- Build configuration: Debug, Vulkan and OpenGL enabled, samples, Perfetto,
  and `fgviewer` disabled; `-O0 -g0`, parallel build of two jobs.
- The C++ test binary in `/root/ManyMesh-build` was freshly configured and
  built from the Linux-filesystem source copy. The `compute_test` build used
  the older E-source build and an out-of-tree Linux shim noted below.

## ManyMesh CPU tests — pass

Built and ran:

```sh
cmake --build /root/mm-cmake-manymesh --target test_manymesh --parallel 2
/root/mm-cmake-manymesh/libs/manymesh/test_manymesh --gtest_color=no
```

Result: **95 tests from 4 suites; 94 passed, 1 skipped; exit code 0**. The
skipped test was `ManyMesh.HttpByteRangeFetcherFeedsTheAsyncCache`.

To verify the D-drive Linux-filesystem source copy, CMake configured with
Clang 17 and exited 0, then built 48/48 Ninja steps. The fresh target was run
as:

```sh
cmake --build /root/ManyMesh-build --target test_manymesh --parallel 2
/root/ManyMesh-build/libs/manymesh/test_manymesh --gtest_color=no
```

It produced the same result: **95 tests from 4 suites; 94 passed, 1 skipped;
exit code 0**. The fresh test runtime was 29.651 seconds. The complete source
copy occupies about 2.5 GiB in the WSL filesystem; D: had 79.6 GiB free after
the copy and build.

## Vulkan compute tests — pass on software device only

Ran:

```sh
/root/mm-cmake-manymesh/filament/backend/compute_test --api=vulkan --gtest_color=no
```

Result: **7/7 passed; exit code 0**. `vulkaninfo` selected `llvmpipe (LLVM
21.1.8, 256 bits)`, Mesa 26.0.8, device type CPU. This verifies the Vulkan
tests under software execution; it is not evidence for Iris Xe GPU behavior or
GPU performance.

## OpenGL compute tests — software failure; hardware path unqualified

With the default llvmpipe OpenGL driver, `compute_test --api=opengl` aborted
with exit code 134. `ComputeTest.copy`, `ComputeTest.manymeshGpuLodNodeTable`,
and `ComputeTest.manymeshGpuCutMatchesCpu` each aborted on a failed handle
assertion. The isolated results were:

| Test | Exit |
|---|---:|
| `basic` | 0 |
| `copy` | 134 |
| `graphicsConsumesComputeOutput` | 0 |
| `drawIndexedIndirect` | 0 |
| `manymeshGpuLodNodeTable` | 134 |
| `manymeshGpuCutMatchesCpu` | 134 |
| `manymeshGpuCutGlesShaderCompiles` | 0 |

Using Mesa's D3D12 OpenGL driver exposed `D3D12 (Intel(R) Iris(R) Xe
Graphics)`, but only at OpenGL 4.1 / Filament feature level 1. The compute test
fixture requires feature level 2, so the hardware-backed run skipped all seven
tests (0 passed, 7 skipped; process exit code 0). It therefore does **not**
verify Iris Xe compute behavior.

## Build accommodations and raw logs

The existing Linux `compute_test` link configuration passed `-lgetopt` even
though glibc provides `getopt`. An out-of-tree CMake hook defined an empty
`getopt` interface target; no repository source or build files were changed.
The existing `filament/backend/src/ostream.cpp:359` switch warning also had to
be demoted from error with `-Wno-error=switch` to build `compute_test`. The
warning concerns the missing `BufferObjectBinding::INDIRECT` diagnostic case;
it was not changed here.

Raw logs for the original build and software/GPU-path diagnostics are in the
ignored directory `out/wsl-local/`. The D-drive reproduction logs are in
`D:\ManyMesh-WSL\` and are also local-only:

- `test-manymesh-final.log`, `build-manymesh-final.log`
- `compute-vulkan.log`, `vulkan-info.txt`
- `compute-opengl.log`, `compute-opengl-individual/summary.txt`
- `compute-opengl-d3d12.log`
- `build-compute-linkfix.log`, `build-compute-relaxed-switch.log`,
  `system-getopt-target.cmake`
- `cmake-d-source.log`, `build-test-manymesh-d.log`,
  `test-manymesh-source-d.log`

## Decision

The ManyMesh CPU unit-test target is locally verified under WSL2. The Vulkan
compute suite passes only on software rendering. OpenGL software failures are
recorded, and the Iris Xe compute route remains unverified because the test
fixture skips at feature level 1. Native Windows execution remains blocked by
Smart App Control. No algorithmic quality gate has passed, so this run does not
advance the research method or establish SIGGRAPH readiness.

## Recheck on 2026-11-27

The existing D-drive distro and environments were available; no Linux packages
needed installation. The compiler is installed as `clang++-17` (there is no
unversioned `clang++` alias), and the project RGB virtual environment already
contains the pinned verification stack: NumPy 2.3.4, SciPy 1.15.3,
scikit-image 0.25.2, Mitsuba 3.9.0, flip-evaluator 1.7, Numba 0.62.1, and
trimesh 4.5.3.

Re-ran the existing binaries in `ManyMesh-Ubuntu-D`:

- `/root/ManyMesh-build/libs/manymesh/test_manymesh --gtest_color=no`:
  95 tests, 94 passed, 1 skipped (`ManyMesh.HttpByteRangeFetcherFeedsTheAsyncCache`),
  exit code 0.
- `/root/mm-cmake-manymesh/filament/backend/compute_test --api=vulkan --gtest_color=no`:
  7/7 passed on Mesa llvmpipe, a CPU software Vulkan device. This is not an
  Iris Xe hardware compute result.

Binary SHA-256 values were `45e241d63349e2791c344a7ff73a70aae0e4db8b22a8e2f9a4a70e8adc7ff969`
for `test_manymesh` and
`68cbb0d7db6c81c7bd749cb3b674392894bfb4370ee487bc6a950465132771fa` for
`compute_test`.

Also re-ran the full independent projective-RGB artifact verifier using the
existing WSL virtual environment on both downloaded CI assets. Both returned
`audit: passed`, with exact expected face counts and source boundaries
preserved: 2,062 faces / 4 boundary edges for GlassHurricaneCandleHolder and
11,350 faces / 1,156 boundary edges for MaterialsVariantsShoe. The verifier
recomputed the stored per-view image means. This verifies the fit artifacts
against their meshoptimizer initialization; it does not overturn the separate
exact-face QEM follow-up, whose development result remains mixed.

The earlier Windows `ArrayMemoryError` and WSL `COMMITMENT_LIMIT` were not
reproduced in this run. A plain process in the restricted tool context received
`Wsl/Service/E_ACCESSDENIED`; invoking the already installed distro through the
permitted host WSL execution path succeeded. No Windows security setting,
Defender exclusion, or distro installation was changed.

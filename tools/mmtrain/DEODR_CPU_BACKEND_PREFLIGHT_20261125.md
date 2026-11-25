# DEODR CPU Backend Preflight

Checked 2026-11-24 UTC as an exploratory alternative to the frozen CUDA
placement control. **No renderer was built, no fit was run, and no image was
scored.** This is an environment feasibility check, not an experiment result.

## Question

Can the public DEODR differentiable CPU renderer run the fixed-topology
placement screen on the current Windows host when CUDA is unavailable?

## Findings

- The host is Windows 11 build 26200. Python 3.12.3 has PyTorch 2.7.1+cpu,
  NumPy 2.5.4, no CUDA runtime, and no DEODR or Cython module. Python 3.10.11
  also has PyTorch 2.7.1+cpu and no CUDA runtime, DEODR, or Cython.
- The only detected C++ compiler is TDM-GCC 9.2.0. Neither `cl` nor `vswhere`
  is available in `PATH`; whether this MinGW toolchain can build the extension
  for either installed Python distribution was not tested.
- The DEODR project builds its Cython extension from
  `deodr/differentiable_renderer_cython.pyx`; its build metadata requires
  Cython and NumPy. The public repository's advertised `master` HEAD at the
  time of the check was `39108e2d09ae06f5f9772856f3f0399e7e704461`.
- `git ls-remote` returned that HEAD, but a shallow clone failed in the
  sandbox with a connection error to its configured local proxy. A retry via
  the elevated network path and another retry with the proxy disabled both
  failed with a connection reset. No source was downloaded into the research
  checkout.

## Decision

The DEODR CPU route was not runnable at the time of this preflight: Cython was
absent, the upstream source could not be fetched, and compiler compatibility
was unknown. Do not treat this as a failed fitting method, a negative quality
result, or a substitute for the frozen nvdiffmodeling control. DEODR's
prior-art relevance and renderer limitations remain documented in the
[SIGGRAPH direction](../../SIGGRAPH_2027_DIRECTION.md).

## Host recheck on 2026-11-25

A later inventory found Visual Studio 2022 at `D:\visual studio 2022`, with
Microsoft-signed MSVC `cl.exe` under
`VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64`. The compiler is not on `PATH`;
the earlier statement that only TDM-GCC was detected describes the initial
preflight, not the current inventory. No Cython package or DEODR checkout was
found in the checked Anaconda environments and package cache. The source fetch
attempts documented above remain unsuccessful. No extension build, fitting,
or image scoring has been performed, so MSVC compatibility is not yet
verified. A compiled extension would still need a policy-compliant loading
path; this recheck does not try to evade Smart App Control.

## Reproduction checks

```powershell
python -c "import importlib.util; print(importlib.util.find_spec('deodr'), importlib.util.find_spec('Cython'))"
git ls-remote https://github.com/martinResearch/DEODR.git HEAD
git clone --depth 1 https://github.com/martinResearch/DEODR.git out/deodr-cpu-probe/source
```

The final command was retried through the elevated network path and with the
configured proxy disabled. All clone attempts failed before checkout. No
package installation or fitting was attempted in this preflight.

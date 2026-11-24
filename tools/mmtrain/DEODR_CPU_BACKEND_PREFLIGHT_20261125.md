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

The DEODR CPU route is **not currently runnable on this host** because Cython
is absent and the upstream source could not be fetched; compiler compatibility
remains untested. Do not treat this as a failed fitting method, a negative
quality result, or a substitute for the frozen nvdiffmodeling control. Revisit
when the source and Cython build dependency are available, first checking
whether the local MinGW toolchain can build the extension, or run the frozen
control on a CUDA-capable host. DEODR's prior-art relevance and renderer
limitations remain documented in the
[SIGGRAPH direction](../../SIGGRAPH_2027_DIRECTION.md).

## Reproduction checks

```powershell
python -c "import importlib.util; print(importlib.util.find_spec('deodr'), importlib.util.find_spec('Cython'))"
git ls-remote https://github.com/martinResearch/DEODR.git HEAD
git clone --depth 1 https://github.com/martinResearch/DEODR.git out/deodr-cpu-probe/source
```

The final command was retried through the elevated network path and with the
configured proxy disabled. All clone attempts failed before checkout. No
package installation or fitting was attempted in this preflight.

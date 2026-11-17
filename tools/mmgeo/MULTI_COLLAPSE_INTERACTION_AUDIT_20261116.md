# Multi-Collapse Filtered-Error Interaction Audit (2026-11-16)

## Protocol

This extends the archived same-view interaction screen from two collapses to 4, 8 and 12 collapses. Each view uses its frozen 48-candidate initial-state pool on the Torus. Every candidate removes exactly two triangles. Candidate sets must have disjoint affected vertex sets, so all schedules at one row reduce the same number of triangles.

For k=2 and k=4, the finite-pool selector is exhaustive over compatible subsets. The independent objective sums each candidate's exact filtered single-collapse SSE. The interaction objective adds all pairwise filtered residual cross terms. For k=8 and k=12, both objectives use deterministic greedy prefixes. Every selected composite is applied to the original mesh and fully rerasterized in the same camera; the pairwise model is compared against this actual composite result.

The score is geometry-only, opaque, coverage plus normalized depth, one orthographic view at a time. It is not an appearance metric or a production legality proof. Frozen candidates do not regenerate after edits, and pairwise one-ring disjointness does not guarantee global self-intersection safety.

## Selected output results

| k | Search | Same schedules / 6 | Mean actual SSE improvement | Views improved | Topology checks / 12 | Max absolute model error |
|---:|---|---:|---:|---:|---:|---:|
| 2 | exact | 6 | 0.000000% | 0 | 12 | 3.76e-19 |
| 4 | exact | 6 | 0.000000% | 0 | 12 | 3.29e-19 |
| 8 | greedy | 6 | 0.000000% | 0 | 12 | 7.32e-19 |
| 12 | greedy | 6 | 0.000000% | 0 | 12 | 2.78e-17 |

At k=12 the schedules remove 24 of the Torus's 1,152 triangles (2.08%). This is a larger budget than the earlier two-collapse screen but remains a small reduction.

| View | k | Selector/search | Triangles removed | Pairwise predicted SSE | Actual composite SSE | Topology check | Candidate IDs |
|---:|---:|---|---:|---:|---:|---|---|
| 0 | 2 | independent / exact | 4 | 3.4111778e-06 | 3.4111778e-06 | pass | `835,2275` |
| 0 | 2 | interaction / exact | 4 | 3.4111778e-06 | 3.4111778e-06 | pass | `835,2275` |
| 0 | 4 | independent / exact | 8 | 1.2229403e-05 | 1.2229403e-05 | pass | `835,1494,2275,2869` |
| 0 | 4 | interaction / exact | 8 | 1.2229403e-05 | 1.2229403e-05 | pass | `835,1494,2275,2869` |
| 0 | 8 | independent / greedy | 16 | 0.00018818243 | 0.00018818243 | pass | `6,540,835,1494,2220,2275,2869,3120` |
| 0 | 8 | interaction / greedy | 16 | 0.00018818243 | 0.00018818243 | pass | `6,540,835,1494,2220,2275,2869,3120` |
| 0 | 12 | independent / greedy | 24 | 0.0040940352 | 0.0040940352 | pass | `6,540,812,835,1494,1656,1701,2220,2275,2869,3083,3120` |
| 0 | 12 | interaction / greedy | 24 | 0.0040940352 | 0.0040940352 | pass | `6,540,812,835,1494,1656,1701,2220,2275,2869,3083,3120` |
| 1 | 2 | independent / exact | 4 | 3.2696082e-06 | 3.2696082e-06 | pass | `1128,1771` |
| 1 | 2 | interaction / exact | 4 | 3.2696082e-06 | 3.2696082e-06 | pass | `1128,1771` |
| 1 | 4 | independent / exact | 8 | 7.3714505e-06 | 7.3714505e-06 | pass | `1128,1771,2419,2869` |
| 1 | 4 | interaction / exact | 8 | 7.3714505e-06 | 7.3714505e-06 | pass | `1128,1771,2419,2869` |
| 1 | 8 | independent / greedy | 16 | 0.00012293911 | 0.00012293911 | pass | `6,540,1128,1494,1771,2065,2419,2869` |
| 1 | 8 | interaction / greedy | 16 | 0.00012293911 | 0.00012293911 | pass | `6,540,1128,1494,1771,2065,2419,2869` |
| 1 | 12 | independent / greedy | 24 | 0.00055167051 | 0.00055167051 | pass | `6,307,540,672,1128,1494,1771,2065,2419,2869,3083,3205` |
| 1 | 12 | interaction / greedy | 24 | 0.00055167051 | 0.00055167051 | pass | `6,307,540,672,1128,1494,1771,2065,2419,2869,3083,3205` |
| 2 | 2 | independent / exact | 4 | 1.2673477e-06 | 1.2673477e-06 | pass | `1289,2275` |
| 2 | 2 | interaction / exact | 4 | 1.2673477e-06 | 1.2673477e-06 | pass | `1289,2275` |
| 2 | 4 | independent / exact | 8 | 8.4923675e-06 | 8.4923675e-06 | pass | `1289,1770,2064,2275` |
| 2 | 4 | interaction / exact | 8 | 8.4923675e-06 | 8.4923675e-06 | pass | `1289,1770,2064,2275` |
| 2 | 8 | independent / greedy | 16 | 0.00015402993 | 0.00015402993 | pass | `541,1039,1289,1567,1770,2064,2275,3121` |
| 2 | 8 | interaction / greedy | 16 | 0.00015402993 | 0.00015402993 | pass | `541,1039,1289,1567,1770,2064,2275,3121` |
| 2 | 12 | independent / greedy | 24 | 0.0040909776 | 0.0040909776 | pass | `541,812,1039,1289,1567,1770,2064,2275,2295,2997,3121,3452` |
| 2 | 12 | interaction / greedy | 24 | 0.0040909776 | 0.0040909776 | pass | `541,812,1039,1289,1567,1770,2064,2275,2295,2997,3121,3452` |
| 3 | 2 | independent / exact | 4 | 3.5158937e-06 | 3.5158937e-06 | pass | `1771,2419` |
| 3 | 2 | interaction / exact | 4 | 3.5158937e-06 | 3.5158937e-06 | pass | `1771,2419` |
| 3 | 4 | independent / exact | 8 | 9.5800491e-06 | 9.5800491e-06 | pass | `1128,1771,2419,2869` |
| 3 | 4 | interaction / exact | 8 | 9.5800491e-06 | 9.5800491e-06 | pass | `1128,1771,2419,2869` |
| 3 | 8 | independent / greedy | 16 | 0.00024975744 | 0.00024975744 | pass | `6,1039,1128,1771,2065,2419,2869,2916` |
| 3 | 8 | interaction / greedy | 16 | 0.00024975744 | 0.00024975744 | pass | `6,1039,1128,1771,2065,2419,2869,2916` |
| 3 | 12 | independent / greedy | 24 | 0.0024015986 | 0.0024015986 | pass | `6,740,1039,1128,1719,1771,2065,2294,2419,2869,2916,3083` |
| 3 | 12 | interaction / greedy | 24 | 0.0024015986 | 0.0024015986 | pass | `6,740,1039,1128,1719,1771,2065,2294,2419,2869,2916,3083` |
| 4 | 2 | independent / exact | 4 | 1.3018724e-06 | 1.3018724e-06 | pass | `1657,2275` |
| 4 | 2 | interaction / exact | 4 | 1.3018724e-06 | 1.3018724e-06 | pass | `1657,2275` |
| 4 | 4 | independent / exact | 8 | 5.8436906e-06 | 5.8436906e-06 | pass | `1657,1770,2275,3161` |
| 4 | 4 | interaction / exact | 8 | 5.8436906e-06 | 5.8436906e-06 | pass | `1657,1770,2275,3161` |
| 4 | 8 | independent / greedy | 16 | 7.6736846e-05 | 7.6736846e-05 | pass | `750,1495,1657,1770,2077,2275,2448,3161` |
| 4 | 8 | interaction / greedy | 16 | 7.6736846e-05 | 7.6736846e-05 | pass | `750,1495,1657,1770,2077,2275,2448,3161` |
| 4 | 12 | independent / greedy | 24 | 0.0043874909 | 0.0043874909 | pass | `307,329,541,750,1495,1657,1770,2077,2275,2448,2717,3161` |
| 4 | 12 | interaction / greedy | 24 | 0.0043874909 | 0.0043874909 | pass | `307,329,541,750,1495,1657,1770,2077,2275,2448,2717,3161` |
| 5 | 2 | independent / exact | 4 | 3.3466869e-06 | 3.3466869e-06 | pass | `1770,2418` |
| 5 | 2 | interaction / exact | 4 | 3.3466869e-06 | 3.3466869e-06 | pass | `1770,2418` |
| 5 | 4 | independent / exact | 8 | 1.0684827e-05 | 1.0684827e-05 | pass | `1567,1770,2418,3370` |
| 5 | 4 | interaction / exact | 8 | 1.0684827e-05 | 1.0684827e-05 | pass | `1567,1770,2418,3370` |
| 5 | 8 | independent / greedy | 16 | 0.00013254161 | 0.00013254161 | pass | `540,1039,1567,1770,2077,2418,2719,3370` |
| 5 | 8 | interaction / greedy | 16 | 0.00013254161 | 0.00013254161 | pass | `540,1039,1567,1770,2077,2418,2719,3370` |
| 5 | 12 | independent / greedy | 24 | 0.0046396162 | 0.0046396162 | pass | `540,739,913,1039,1274,1567,1770,2077,2418,2719,3344,3370` |
| 5 | 12 | interaction / greedy | 24 | 0.0046396162 | 0.0046396162 | pass | `540,739,913,1039,1274,1567,1770,2077,2418,2719,3344,3370` |

Composite rasterization took 2.396s total in this Python CPU diagnostic; complete analysis took 6.263s. These times only show experiment cost and are not comparable to a production simplifier.

## Decision

A multi-collapse result is useful only if the interaction-aware selector changes actual output quality at the same triangle budget, the gain is stable across views, and the work to obtain the scores is cheaper than exact local redraw. Read the table together with the limitations and machine-readable schedules; exact k=2/4 selectors are finite-pool offline oracles, while k=8/12 are greedy controls. No general mesh, attribute, runtime, or SIGGRAPH claim follows from this single Torus experiment.

Machine-readable results and hashes: `out\multi-collapse-interactions-20261116\torus.json`.

# New Khronos candidate quality screen protocol

Frozen before running image-quality scoring. This is a development-pool screen, not confirmation data.

- Assets: AnisotropyBarnLamp, DiffuseTransmissionTeacup, GlassBrokenWindow, GlassHurricaneCandleHolder, MaterialsVariantsShoe, PotOfCoals, and SpecularSilkPouf. Source OBJ hashes are in `protocol.json`. ABeautifulGame is excluded because it failed the topology gate; it will not be repaired or filtered.
- Methods: current ManyMesh DAG cut, whole-mesh fast-simplification QEM, and vendored meshoptimizer with LockBorder. For each actual DAG face count, simplify the full source to that exact count; reject count mismatches or any topology/boundary failure before image scoring.
- Requested DAG targets: 30%, 50%, and 70%. Report actual retained face counts; a missed target is not silently relabeled.
- Reference: full-resolution static default-scene geometry extracted with node transforms. Materials and animation are omitted.
- Image protocol: eight fixed orthographic views, flat shading, 192 x 192, four CPU software samples per pixel. These are not hardware MSAA samples. Report LDR-FLIP (67 pixels/degree), PSNR, SSIM, silhouette XOR, and coverage MAE.
- Surface protocol: 10,000 area-uniform samples per direction; report sampled Chamfer, 95th-percentile distance, and normal consistency.
- Report every asset and view. Views are repeated measurements of an asset, not independent samples. No aggregate significance claim. No parameter tuning against these candidate assets.
- No frame-time, mobile, temporal, user-preference, differentiable-optimization, or held-out claim follows from this run.

Tool, source, and dependency hashes are recorded in the JSON receipts and per-run outputs.

The mmgeo build writes position-only PLY while the existing scoring loader expects unused normal/UV fields. A frozen adapter copies every position and face byte unchanged, appends zero values only for those unused fields, and records input/output hashes before scoring.

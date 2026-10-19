/*
 * Copyright (C) 2026 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef TNT_MANYMESH_SHADINGNORMALS_H
#define TNT_MANYMESH_SHADINGNORMALS_H

#include <manymesh/Mesh.h>

#include <stddef.h>

namespace filament {
namespace manymesh {

struct ShadingNormalOptions {
    //! Duplicate-position normals closer than this angle are averaged. Normals farther apart
    //! than the angle are left alone, so intentional hard edges survive. 0 disables the pass.
    float creaseAngleDegrees = 25.0f;

    //! Positions within this distance are treated as duplicates. 0 derives the epsilon from the
    //! mesh bounds (1e-6 of the diagonal, with a small absolute floor).
    float positionEpsilon = 0.0f;

    //! Blend factor toward the cluster average, in [0, 1]. 0 leaves the source normals
    //! untouched; 1 applies the full seam repair described above.
    float strength = 1.0f;
};

/**
 * Recommended normal-repair blend for a given worst-case screen-space geometric error.
 *
 * A seam normal change below a quarter pixel is invisible, so the pass starts at 0. It ramps
 * smoothly to the measured optimum of 0.5 at one pixel and stays there. Going to 1.0 removes
 * slightly more seam shading but also flattens real normal variation; on the 38-62% monkey
 * cuts that cost 0.08-0.10 dB versus 0.5.
 */
float recommendedShadingNormalStrength(float screenErrorPx) noexcept;

/**
 * Per-cluster weight for baked shading compensation such as AO, bent normals, detail normals
 * and parallax.
 *
 * A cluster whose worst-case geometric error is below a quarter pixel does not need a
 * compensation texture: its own vertices already carry the source detail. The weight ramps
 * smoothly to 1 at one pixel, then stays there. Used as a vertex attribute, it lets a cut mix
 * fine near clusters and coarse far clusters without either paying for or suffering from
 * compensation that does not apply to it.
 *
 * This is a shading weight, not a quality gate. The global compensation strength still
 * multiplies it, so 0 disables all compensation.
 */
float recommendedShadingCompensationWeight(float screenErrorPx) noexcept;

/**
 * The measured LOD shading ladder for a retained triangle ratio.
 *
 * `retainedRatio` is the fraction of source triangles in the cut, in [0, 1]. The ladder was
 * measured on monkey, torus and cloth at 960x720 with matching AO references:
 *
 * - At 45% and above, source-mesh AO 0.5 plus 10-degree/auto seam normals is the only
 *   repeatable surface gain. MSAA is left to the caller because the AO tier already pays for
 *   the cut's geometry.
 * - Below 45%, AO becomes blocky on large triangles and detail normals regress. The stable
 *   combination is 4x MSAA plus 10-degree/auto seam normals; AO and micro-normal terms stay
 *   off.
 *
 * `hasCompensationMaterial` is false when the selected material cannot sample AO. In that case
 * the ladder never requests AO, even if the ratio would otherwise qualify.
 *
 * This is a shading recommendation, not a geometry quality gate: it changes no triangle and
 * cannot restore silhouettes, thin features or displaced surfaces.
 */
struct ShadingCompensationPreset {
    bool useAmbientOcclusion = false;
    float ambientOcclusionStrength = 0.0f;
    //! When true the caller should enable `msaaSamples`; false leaves its current AA setting.
    bool enableMsaa = false;
    int msaaSamples = 4;
    float normalCreaseDegrees = 10.0f;
    bool autoNormalStrength = true;
    float normalStrength = 0.5f;
};

ShadingCompensationPreset recommendedShadingCompensationPreset(float retainedRatio,
        bool hasCompensationMaterial) noexcept;

struct ShadingNormalResult {
    //! Duplicate vertices found beyond the first vertex in each position group.
    size_t duplicateVertices = 0;

    //! Clusters of two or more duplicate vertices that were averaged.
    size_t mergedClusters = 0;

    //! Vertices whose normal actually changed.
    size_t changedVertices = 0;

    //! Largest angle between an original normal and the normal it was replaced with.
    float maxMergedAngleDegrees = 0.0f;
};

/**
 * Makes shading normals continuous across duplicated vertices that lie at the same position.
 *
 * Simplification and UV/normal seam splitting leave several vertices at one position. They are
 * necessary for correct attributes, but if their normals differ by a few degrees the LOD shows
 * visible shading facets along the seam. This pass builds position groups, clusters their
 * normals by angle, and replaces each cluster with its angle-weighted average. Groups whose
 * normals are separated by more than `creaseAngleDegrees` stay split, so creases are preserved.
 *
 * `indices` are used for the angle weights and do not have to cover every vertex. Vertices
 * outside the index set still participate in position grouping, with a small fallback weight.
 */
void repairShadingNormals(Mesh* mesh, std::vector<uint32_t> const& indices,
        ShadingNormalOptions const& options, ShadingNormalResult* result = nullptr);

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_SHADINGNORMALS_H


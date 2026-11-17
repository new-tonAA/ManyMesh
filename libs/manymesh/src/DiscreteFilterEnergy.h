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

#ifndef MANYMESH_DISCRETEFILTERENERGY_H
#define MANYMESH_DISCRETEFILTERENERGY_H

#include <array>
#include <cstddef>
#include <vector>

namespace filament::manymesh::details {

// Difference at an actual high-resolution raster sample; no visibility approximation here.
// Coordinates are in the full supersampled viewport. Duplicate coordinates are allowed and add.
struct RasterDelta {
    int x;
    int y;
    std::array<double, 2> value;
};

// Research-only fixed-camera, two-channel Gaussian+box-downsample error accumulator.
// The finite image boundary, truncated filter and sample/downsample phase are represented exactly
// up to floating arithmetic. Does NOT model nonlinear TAA, shaders, or continuous coverage.
// Mutable instances require external exclusive ownership; no shared global state.
class DiscreteFilterEnergy {
public:
    // Invalid dimensions/sigma leave an invalid instance. Output dimensions are limited to 8192,
    // scale to 16 and Gaussian radius to 128 input samples to bound accidental allocation.
    DiscreteFilterEnergy(int width, int height, int scale, double sigma);
    bool valid() const noexcept { return mValid; }

    // Score E(r + Fd) - E(r). Pairwise Gram kernel: no candidate output image allocation.
    // Invalid input returns NaN. For large/dense deltas use evaluateSplat instead (O(N^2) pairs).
    double evaluateGram(std::vector<RasterDelta> const& delta) const;

    // Strong baseline: scatter exact sparse impulses to a tight output patch, then evaluate loss.
    // Reuses mutable per-instance scratch; does not change residual/history.
    double evaluateSplat(std::vector<RasterDelta> const& delta);

    // Commit delta with sign +1; sign -1 undoes its linear image effect. Caller must keep camera,
    // filter and geometry identities consistent. This is NOT a mesh topology undo operation.
    bool apply(std::vector<RasterDelta> const& delta, double sign = 1.0);
    double energy() const;
    std::vector<std::array<double, 2>> const& residual() const noexcept { return mResidual; }
    size_t persistentBytes() const noexcept;

private:
    struct AxisWeights {
        int first = 0;
        std::vector<double> weights;
    };
    static std::vector<AxisWeights> makeAxis(int outputs, int scale,
            std::vector<double> const& kernel);
    static double inner(AxisWeights const& a, AxisWeights const& b) noexcept;
    bool validate(std::vector<RasterDelta> const& delta) const noexcept;
    double linearTerm(RasterDelta const& event) const noexcept;
    int mWidth = 0;
    int mHeight = 0;
    bool mValid = false;
    std::vector<AxisWeights> mX;
    std::vector<AxisWeights> mY;
    std::vector<std::array<double, 2>> mResidual;
    std::vector<std::array<double, 2>> mScratch;
};

} // namespace filament::manymesh::details

#endif // MANYMESH_DISCRETEFILTERENERGY_H

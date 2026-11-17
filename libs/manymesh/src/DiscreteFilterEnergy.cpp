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

#include "DiscreteFilterEnergy.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace filament::manymesh::details {

std::vector<DiscreteFilterEnergy::AxisWeights> DiscreteFilterEnergy::makeAxis(
        int outputs, int scale, std::vector<double> const& kernel) {
    int const radius = int(kernel.size() / 2);
    std::vector<AxisWeights> result(size_t(outputs * scale));
    for (int source = 0; source < outputs * scale; ++source) {
        auto& axis = result[source];
        int const low = std::max(0, source - radius);
        int const high = std::min(outputs * scale - 1, source + radius);
        axis.first = low / scale;
        axis.weights.assign(size_t(high / scale - axis.first + 1), 0.0);
        for (int sample = low; sample <= high; ++sample) {
            axis.weights[sample / scale - axis.first] += kernel[sample - source + radius] / scale;
        }
    }
    return result;
}

DiscreteFilterEnergy::DiscreteFilterEnergy(int width, int height, int scale, double sigma) {
    if (width < 1 || height < 1 || width > 8192 || height > 8192 || scale < 1 || scale > 16 ||
            !std::isfinite(sigma) || sigma <= 0.0 || 4.0 * sigma * scale > 128.0) {
        return;
    }
    mWidth = width;
    mHeight = height;
    int const radius = int(std::ceil(4.0 * sigma * scale));
    std::vector<double> kernel(size_t(2 * radius + 1));
    double sum = 0.0;
    for (int i = -radius; i <= radius; ++i) {
        double const distance = i / (sigma * scale);
        kernel[i + radius] = std::exp(-0.5 * distance * distance);
        sum += kernel[i + radius];
    }
    for (double& weight: kernel) { weight /= sum; }
    mX = makeAxis(width, scale, kernel);
    mY = makeAxis(height, scale, kernel);
    mResidual.resize(size_t(width) * height, { 0.0, 0.0 });
    mValid = true;
}

bool DiscreteFilterEnergy::validate(std::vector<RasterDelta> const& delta) const noexcept {
    if (!mValid) { return false; }
    for (auto const& e: delta) {
        if (e.x < 0 || e.y < 0 || size_t(e.x) >= mX.size() || size_t(e.y) >= mY.size() ||
                !std::isfinite(e.value[0]) || !std::isfinite(e.value[1])) {
            return false;
        }
    }
    return true;
}

double DiscreteFilterEnergy::inner(AxisWeights const& a, AxisWeights const& b) noexcept {
    int const first = std::max(a.first, b.first);
    int const last = std::min(a.first + int(a.weights.size()), b.first + int(b.weights.size()));
    double result = 0.0;
    for (int i = first; i < last; ++i) { result += a.weights[i-a.first] * b.weights[i-b.first]; }
    return result;
}

double DiscreteFilterEnergy::linearTerm(RasterDelta const& e) const noexcept {
    auto const& xs = mX[e.x];
    auto const& ys = mY[e.y];
    double result = 0.0;
    for (size_t y = 0; y < ys.weights.size(); ++y) {
        for (size_t x = 0; x < xs.weights.size(); ++x) {
            auto const& r = mResidual[size_t(ys.first + int(y)) * mWidth + xs.first + x];
            result += xs.weights[x] * ys.weights[y] * (r[0] * e.value[0] + r[1] * e.value[1]);
        }
    }
    return result;
}

double DiscreteFilterEnergy::evaluateGram(std::vector<RasterDelta> const& delta) const {
    if (!validate(delta)) { return std::numeric_limits<double>::quiet_NaN(); }
    double result = 0.0;
    for (size_t i = 0; i < delta.size(); ++i) {
        auto const& a = delta[i];
        result += 2.0 * linearTerm(a);
        for (size_t j = i; j < delta.size(); ++j) {
            auto const& b = delta[j];
            double const kx = inner(mX[a.x], mX[b.x]);
            if (kx == 0.0) { continue; }
            double const ky = inner(mY[a.y], mY[b.y]);
            double const dot = a.value[0] * b.value[0] + a.value[1] * b.value[1];
            result += (i == j ? 1.0 : 2.0) * kx * ky * dot;
        }
    }
    return result;
}

double DiscreteFilterEnergy::evaluateSplat(std::vector<RasterDelta> const& delta) {
    if (!validate(delta)) { return std::numeric_limits<double>::quiet_NaN(); }
    if (delta.empty()) { return 0.0; }
    int x0 = mWidth, y0 = mHeight, x1 = 0, y1 = 0;
    for (auto const& e: delta) {
        x0 = std::min(x0, mX[e.x].first); y0 = std::min(y0, mY[e.y].first);
        x1 = std::max(x1, mX[e.x].first + int(mX[e.x].weights.size()));
        y1 = std::max(y1, mY[e.y].first + int(mY[e.y].weights.size()));
    }
    size_t const width = size_t(x1-x0);
    mScratch.assign(width * size_t(y1-y0), { 0.0, 0.0 });
    for (auto const& e: delta) {
        auto const& xs = mX[e.x]; auto const& ys = mY[e.y];
        for (size_t y = 0; y < ys.weights.size(); ++y) {
            for (size_t x = 0; x < xs.weights.size(); ++x) {
                double const w = xs.weights[x] * ys.weights[y];
                auto& value = mScratch[size_t(ys.first + int(y)-y0) * width + xs.first + x-x0];
                value[0] += w * e.value[0]; value[1] += w * e.value[1];
            }
        }
    }
    double result = 0.0;
    for (int y = y0; y < y1; ++y) {
        for (int x = x0; x < x1; ++x) {
            auto const& d = mScratch[size_t(y-y0)*width + x-x0];
            auto const& r = mResidual[size_t(y)*mWidth + x];
            result += 2.0*(r[0]*d[0]+r[1]*d[1])+d[0]*d[0]+d[1]*d[1];
        }
    }
    return result;
}

bool DiscreteFilterEnergy::apply(std::vector<RasterDelta> const& delta, double sign) {
    if (!validate(delta) || !std::isfinite(sign)) { return false; }
    for (auto const& e: delta) {
        auto const& xs = mX[e.x]; auto const& ys = mY[e.y];
        for (size_t y = 0; y < ys.weights.size(); ++y) {
            for (size_t x = 0; x < xs.weights.size(); ++x) {
                double const w = sign * xs.weights[x] * ys.weights[y];
                auto& value = mResidual[size_t(ys.first + int(y))*mWidth + xs.first + x];
                value[0] += w * e.value[0]; value[1] += w * e.value[1];
            }
        }
    }
    return true;
}

double DiscreteFilterEnergy::energy() const {
    if (!mValid) { return std::numeric_limits<double>::quiet_NaN(); }
    double result = 0.0;
    for (auto const& r: mResidual) { result += r[0]*r[0]+r[1]*r[1]; }
    return result;
}

size_t DiscreteFilterEnergy::persistentBytes() const noexcept {
    size_t result = mResidual.capacity() * sizeof(mResidual[0]);
    for (auto const* axis: { &mX, &mY }) {
        result += axis->capacity() * sizeof(AxisWeights);
        for (auto const& a: *axis) { result += a.weights.capacity() * sizeof(double); }
    }
    return result; // excludes allocator overhead and reusable evaluation scratch
}

} // namespace filament::manymesh::details

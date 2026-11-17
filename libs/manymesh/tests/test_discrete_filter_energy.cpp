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

#include "../src/DiscreteFilterEnergy.h"

#include <gtest/gtest.h>

#include <array>
#include <cmath>
#include <limits>
#include <random>
#include <vector>

using namespace filament::manymesh::details;

namespace {
using Pixel = std::array<double, 2>;
// Independent dense implementation: explicit convolution followed by box reduction.
std::vector<Pixel> reference(int width, int height, int scale, double sigma,
        std::vector<RasterDelta> const& delta) {
    int const w = width*scale, h = height*scale;
    std::vector<Pixel> image(size_t(w)*h, { 0.0, 0.0 });
    for (auto const& e: delta) {
        for (int c = 0; c < 2; ++c) { image[size_t(e.y)*w+e.x][c] += e.value[c]; }
    }
    int const radius = int(std::ceil(4*sigma*scale));
    std::vector<double> kernel(size_t(2*radius+1));
    double sum = 0.0;
    for (int k = -radius; k <= radius; ++k) {
        kernel[k+radius] = std::exp(-0.5*std::pow(k/(sigma*scale), 2));
        sum += kernel[k+radius];
    }
    for (double& k: kernel) { k /= sum; }
    for (int axis = 0; axis < 2; ++axis) {
        std::vector<Pixel> filtered(image.size(), { 0.0, 0.0 });
        for (int y = 0; y < h; ++y) {
            for (int x = 0; x < w; ++x) {
                for (int k = -radius; k <= radius; ++k) {
                    int const sx = x+(axis == 0 ? k : 0), sy = y+(axis == 1 ? k : 0);
                    if (sx < 0 || sy < 0 || sx >= w || sy >= h) { continue; }
                    for (int c = 0; c < 2; ++c) {
                        filtered[size_t(y)*w+x][c] += kernel[k+radius]*image[size_t(sy)*w+sx][c];
                    }
                }
            }
        }
        image.swap(filtered);
    }
    std::vector<Pixel> output(size_t(width)*height, { 0.0, 0.0 });
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            for (int c = 0; c < 2; ++c) {
                output[size_t(y/scale)*width+x/scale][c] += image[size_t(y)*w+x][c]/(scale*scale);
            }
        }
    }
    return output;
}

double norm(std::vector<Pixel> const& image) {
    double sum = 0.0;
    for (auto const& p: image) { sum += p[0]*p[0]+p[1]*p[1]; }
    return sum;
}
} // namespace

TEST(DiscreteFilterEnergy, MatchesDenseConvolutionAtEdgesAndAllSamplePhases) {
    for (int scale: { 1, 2, 3, 4 }) {
        for (double sigma: { 0.2, 0.9, 1.7 }) {
            DiscreteFilterEnergy accumulator(7, 5, scale, sigma);
            ASSERT_TRUE(accumulator.valid());
            for (int phase = 0; phase < scale; ++phase) {
                std::vector<RasterDelta> events = {
                    { 0, 0, { 1.0, 0.3 } }, { 7*scale-1, 5*scale-1, { -0.4, 0.6 } },
                    { 3*scale+phase, 2*scale+phase, { 0.2, -0.5 } },
                    { 3*scale+phase, 2*scale+phase, { -0.1, 0.1 } }
                };
                auto const expected = reference(7, 5, scale, sigma, events);
                EXPECT_NEAR(accumulator.evaluateGram(events), norm(expected), 1e-12);
                EXPECT_NEAR(accumulator.evaluateSplat(events), norm(expected), 1e-12);
                ASSERT_TRUE(accumulator.apply(events));
                for (size_t i = 0; i < expected.size(); ++i) {
                    EXPECT_NEAR(accumulator.residual()[i][0], expected[i][0], 1e-13);
                    EXPECT_NEAR(accumulator.residual()[i][1], expected[i][1], 1e-13);
                }
                EXPECT_NEAR(accumulator.energy(), norm(expected), 1e-12);
                ASSERT_TRUE(accumulator.apply(events, -1.0));
                EXPECT_NEAR(accumulator.energy(), 0.0, 1e-26);
            }
        }
    }
}

TEST(DiscreteFilterEnergy, CumulativeRandomChangesAndCancellation) {
    DiscreteFilterEnergy accumulator(16, 12, 3, 0.9);
    std::mt19937 rng(731);
    std::uniform_real_distribution<double> value(-1.0, 1.0);
    std::vector<RasterDelta> history;
    for (int iteration = 0; iteration < 12; ++iteration) {
        std::vector<RasterDelta> events;
        for (int i = 0; i < 10; ++i) {
            events.push_back({ int(rng()%48), int(rng()%36), { value(rng), value(rng) } });
        }
        double const before = norm(reference(16, 12, 3, 0.9, history));
        history.insert(history.end(), events.begin(), events.end());
        double const expected = norm(reference(16, 12, 3, 0.9, history))-before;
        EXPECT_NEAR(accumulator.evaluateGram(events), expected, 1e-11);
        EXPECT_NEAR(accumulator.evaluateSplat(events), expected, 1e-11);
        ASSERT_TRUE(accumulator.apply(events));
    }
    auto inverse = history;
    for (auto& e: inverse) { e.value[0] *= -1; e.value[1] *= -1; }
    EXPECT_NEAR(accumulator.evaluateGram(inverse), -accumulator.energy(), 1e-11);
    ASSERT_TRUE(accumulator.apply(inverse));
    EXPECT_NEAR(accumulator.energy(), 0.0, 1e-26);
}

TEST(DiscreteFilterEnergy, InvalidInputDoesNotModifyResidual) {
    DiscreteFilterEnergy accumulator(8, 8, 3, 0.9);
    std::vector<RasterDelta> invalid = { { -1, 0, { 1.0, 0.0 } } };
    EXPECT_TRUE(std::isnan(accumulator.evaluateGram(invalid)));
    EXPECT_TRUE(std::isnan(accumulator.evaluateSplat(invalid)));
    EXPECT_FALSE(accumulator.apply(invalid));
    EXPECT_DOUBLE_EQ(accumulator.energy(), 0.0);
    invalid[0] = { 0, 0, { std::numeric_limits<double>::infinity(), 0.0 } };
    EXPECT_FALSE(accumulator.apply(invalid));
    EXPECT_DOUBLE_EQ(accumulator.energy(), 0.0);
    EXPECT_FALSE(DiscreteFilterEnergy(0, 1, 1, 1.0).valid());
    EXPECT_FALSE(DiscreteFilterEnergy(8, 8, 0, 1.0).valid());
    EXPECT_FALSE(DiscreteFilterEnergy(8, 8, 3, -1.0).valid());
    EXPECT_FALSE(DiscreteFilterEnergy(8, 8, 3, 100.0).valid());
}

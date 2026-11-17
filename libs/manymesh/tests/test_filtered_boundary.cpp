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

#include "../src/FilteredBoundaryError.h"

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <limits>

using namespace filament::manymesh::details;

namespace {
// Independent image integration, not evaluation of the analytic loss formula.
double integrateResidual(double a0, double a1, double b0, double b1, double sigma) {
    double const lower = std::min({ a0, a1, b0, b1 }) - 10.0 * sigma;
    double const upper = std::max({ a0, a1, b0, b1 }) + 10.0 * sigma;
    constexpr int SAMPLES = 32768;
    double const step = (upper - lower) / SAMPLES;
    auto cdf = [sigma](double x) { return 0.5 * std::erfc(-x / (sigma * std::sqrt(2.0))); };
    double sum = 0.0;
    for (int i = 0; i < SAMPLES; ++i) {
        double const x = lower + (i + 0.5) * step;
        sum += (cdf(x - a0) - cdf(x - a1)) * (cdf(x - b0) - cdf(x - b1));
    }
    return sum * step;
}
} // namespace

TEST(FilteredBoundary, MatchesIndependentImageIntegral) {
    for (double sigma: { 0.125, 0.5, 2.0 }) {
        for (double d: { -4.0, -0.2, -0.001, 0.0, 0.001, 0.2, 4.0 }) {
            auto const result = filteredBoundaryLoss(d, sigma);
            EXPECT_NEAR(result.value, integrateResidual(0.0, d, 0.0, d, sigma), 1e-10);
            EXPECT_GE(result.value, 0.0);
        }
    }
}

TEST(FilteredBoundary, DerivativesAndLimits) {
    double const sigma = 0.5;
    for (double d: { -1.0, -0.2, 0.0, 0.2, 1.0 }) {
        double const h = 1e-5;
        auto const result = filteredBoundaryLoss(d, sigma);
        auto const left = filteredBoundaryLoss(d - h, sigma);
        auto const right = filteredBoundaryLoss(d + h, sigma);
        EXPECT_NEAR(result.gradient, (right.value - left.value) / (2.0 * h), 1e-9);
        EXPECT_NEAR(result.curvature, (right.gradient - left.gradient) / (2.0 * h), 1e-9);
        EXPECT_GT(result.curvature, 0.0);
    }
    auto const tiny = filteredBoundaryLoss(1e-10, sigma);
    EXPECT_NEAR(tiny.value / 1e-20, 1.0 / (2.0 * sigma * std::sqrt(std::acos(-1.0))),
            1e-14);
    EXPECT_NEAR(filteredBoundaryLoss(10.0, 1e-9).value, 10.0, 2e-9);
    EXPECT_DOUBLE_EQ(filteredBoundaryLoss(0.0, sigma).value, 0.0);
}

TEST(FilteredBoundary, InteractionMatchesIndependentImageIntegral) {
    for (double sigma: { 0.125, 0.5, 2.0 }) {
        for (double offset: { -4.0, -0.3, 0.0, 0.3, 4.0 }) {
            for (double motion: { -2.0, -0.2, 0.001, 0.2, 2.0 }) {
                double const actual = filteredBoundaryInteraction(
                        0.0, motion, offset, offset + 0.15, sigma);
                double const expected = integrateResidual(
                        0.0, motion, offset, offset + 0.15, sigma);
                EXPECT_NEAR(actual, expected, 2e-8);
                EXPECT_NEAR(actual, filteredBoundaryInteraction(
                        offset, offset + 0.15, 0.0, motion, sigma), 1e-12);
                EXPECT_NEAR(-actual, filteredBoundaryInteraction(
                        motion, 0.0, offset, offset + 0.15, sigma), 1e-12);
            }
        }
    }
}

TEST(FilteredBoundary, ThinStructureRequiresCrossTerm) {
    double const sigma = 0.5;
    double const independent = 2.0 * filteredBoundaryLoss(0.2, sigma).value;
    double const interaction = filteredBoundaryInteraction(0.0, 0.2, 0.3, 0.5, sigma);
    double const coupled = independent - 2.0 * interaction;
    double const reference = integrateResidual(0.0, 0.2, 0.0, 0.2, sigma) +
            integrateResidual(0.3, 0.5, 0.3, 0.5, sigma) -
            2.0 * integrateResidual(0.0, 0.2, 0.3, 0.5, sigma);
    EXPECT_NEAR(coupled, reference, 1e-9);
    EXPECT_GT(coupled, 0.0);
    EXPECT_GT(independent / coupled, 11.0);
    EXPECT_NEAR(coupled, 0.003810298, 1e-9);
}

TEST(FilteredBoundary, TinyMotionsDoNotCancelNumerically) {
    double const da = 1e-8;
    double const db = -2e-8;
    double const offset = 0.3;
    double const sigma = 0.5;
    double const result = filteredBoundaryInteraction(0.0, da, offset, offset + db, sigma);
    double const representedDb = (offset + db) - offset;
    double const leading = da * representedDb / (2.0 * sigma * std::sqrt(std::acos(-1.0))) *
            std::exp(-offset * offset / (4.0 * sigma * sigma));
    EXPECT_NEAR(result / leading, 1.0, 2e-8);
}

TEST(FilteredBoundary, TranslationAndPositiveSemidefiniteGram) {
    double const sigma = 0.5;
    double const starts[] = { -0.5, 0.0, 0.3, 1.5 };
    double const ends[] = { -0.1, -0.2, 0.5, 2.5 };
    for (int mask = 0; mask < 16; ++mask) {
        double loss = 0.0;
        for (int i = 0; i < 4; ++i) {
            for (int j = 0; j < 4; ++j) {
                double const sign = ((mask >> i) & 1) == ((mask >> j) & 1) ? 1.0 : -1.0;
                double const value = filteredBoundaryInteraction(
                        starts[i], ends[i], starts[j], ends[j], sigma);
                loss += sign * value;
                EXPECT_NEAR(value, filteredBoundaryInteraction(starts[i] + 100.0,
                        ends[i] + 100.0, starts[j] + 100.0, ends[j] + 100.0, sigma), 1e-12);
            }
        }
        EXPECT_GE(loss, -1e-8);
    }
}

TEST(FilteredBoundary, RejectsInvalidInputs) {
    double const inf = std::numeric_limits<double>::infinity();
    double const nan = std::numeric_limits<double>::quiet_NaN();
    for (double sigma: { -1.0, 0.0, inf, nan }) {
        auto const loss = filteredBoundaryLoss(1.0, sigma);
        EXPECT_TRUE(std::isnan(loss.value));
        EXPECT_TRUE(std::isnan(loss.gradient));
        EXPECT_TRUE(std::isnan(loss.curvature));
        EXPECT_TRUE(std::isnan(filteredBoundaryInteraction(0.0, 0.2, 0.3, 0.5, sigma)));
    }
    EXPECT_TRUE(std::isnan(filteredBoundaryLoss(inf, 0.5).value));
    EXPECT_TRUE(std::isnan(filteredBoundaryLoss(nan, 0.5).value));
    EXPECT_TRUE(std::isnan(filteredBoundaryInteraction(0.0, inf, 0.0, 0.2, 0.5)));
    EXPECT_TRUE(std::isnan(filteredBoundaryInteraction(nan, 0.1, 0.0, 0.2, 0.5)));
}

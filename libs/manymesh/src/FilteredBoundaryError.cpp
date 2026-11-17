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

#include "FilteredBoundaryError.h"

#include <cmath>
#include <limits>

namespace filament::manymesh::details {
namespace {
constexpr double INV_SQRT_PI = 0.56418958354775628695;
constexpr double NAN_VALUE = std::numeric_limits<double>::quiet_NaN();

bool validSigma(double sigma) noexcept {
    return std::isfinite(sigma) && sigma > 0.0;
}
} // namespace

FilteredBoundaryLoss filteredBoundaryLoss(double displacement, double sigma) noexcept {
    if (!std::isfinite(displacement) || !validSigma(sigma)) {
        return { NAN_VALUE, NAN_VALUE, NAN_VALUE };
    }
    double const distance = std::abs(displacement);
    double const u = (distance / sigma) * 0.5;
    double value;
    if (u < 1e-3) {
        // Avoid cancellation between the erf and exponential terms near zero.
        double const u2 = u * u;
        value = distance * INV_SQRT_PI * u *
                (1.0 + u2 * (-1.0 / 6.0 + u2 * (1.0 / 30.0 - u2 / 168.0)));
    } else {
        // Multiply sigma after the bounded coefficient, avoiding overflow of 2*sigma.
        value = distance * std::erf(u) +
                sigma * (2.0 * INV_SQRT_PI * std::expm1(-u * u));
    }
    return { value, std::copysign(std::erf(u), displacement),
            (INV_SQRT_PI * std::exp(-u * u)) / sigma };
}

double filteredBoundaryInteraction(double a0, double a1, double b0, double b1,
        double sigma) noexcept {
    if (!validSigma(sigma) || !std::isfinite(a0) || !std::isfinite(a1) ||
            !std::isfinite(b0) || !std::isfinite(b1)) {
        return NAN_VALUE;
    }
    double const da = a1 - a0;
    double const db = b1 - b0;
    double const offset = a0 - b0;
    if (!std::isfinite(da) || !std::isfinite(db) || !std::isfinite(offset)) {
        return NAN_VALUE;
    }
    if (da == 0.0 || db == 0.0) {
        return 0.0;
    }
    if (a0 == b0 && a1 == b1) {
        return filteredBoundaryLoss(da, sigma).value;
    }
    if (std::abs(da) <= sigma && std::abs(db) <= sigma) {
        // Integrate G_{sqrt(2)*sigma}(s-t) over the two oriented motion intervals.
        // Four-point Gauss-Legendre in each dimension, mapped to [0,1]. Translation is
        // removed before sampling so large absolute screen coordinates do not lose the motion.
        constexpr double NODES[] = {
            0.06943184420297371, 0.33000947820757187,
            0.66999052179242813, 0.93056815579702629
        };
        constexpr double WEIGHTS[] = {
            0.17392742256872693, 0.32607257743127307,
            0.32607257743127307, 0.17392742256872693
        };
        double sum = 0.0;
        for (int i = 0; i < 4; ++i) {
            for (int j = 0; j < 4; ++j) {
                double const u = 0.5 * (offset / sigma +
                        (da / sigma) * NODES[i] - (db / sigma) * NODES[j]);
                sum += WEIGHTS[i] * WEIGHTS[j] * std::exp(-u * u);
            }
        }
        return da * (db / sigma) * (0.5 * INV_SQRT_PI * sum);
    }
    double const distances[] = { a0 - b1, a1 - b0, a0 - b0, a1 - b1 };
    for (double distance: distances) {
        if (!std::isfinite(distance)) {
            return NAN_VALUE;
        }
    }
    // Half each term before summing to avoid overflowing the intermediate sum.
    return 0.5 * filteredBoundaryLoss(distances[0], sigma).value +
            0.5 * filteredBoundaryLoss(distances[1], sigma).value -
            0.5 * filteredBoundaryLoss(distances[2], sigma).value -
            0.5 * filteredBoundaryLoss(distances[3], sigma).value;
}

} // namespace filament::manymesh::details

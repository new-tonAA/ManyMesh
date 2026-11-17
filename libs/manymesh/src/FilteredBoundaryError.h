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

#ifndef MANYMESH_FILTEREDBOUNDARYERROR_H
#define MANYMESH_FILTEREDBOUNDARYERROR_H

namespace filament::manymesh::details {

// Experimental, continuous image-space model, NOT a geometry error bound. Positions and sigma
// are in pixels. Assumes parallel straight boundaries with constant colors and the same Gaussian
// filter. Integrals are per unit screen-space boundary length, without color or length weights.
struct FilteredBoundaryLoss {
    double value;
    double gradient;
    double curvature;
};

// Integral of the squared difference of two Gaussian-filtered unit steps separated by displacement.
// Requires finite displacement and finite sigma > 0. Invalid input returns NaN in all fields.
FilteredBoundaryLoss filteredBoundaryLoss(double displacement, double sigma) noexcept;

// Inner product of two step-motion residuals: (step(a0)-step(a1)) * (step(b0)-step(b1)).
// Signed: reversing one motion reverses the result. Equal motions yield filteredBoundaryLoss.
// Nearby subpixel motions use quadrature of the Gaussian autocorrelation to avoid subtracting
// almost equal losses. Other cases use the closed form. Invalid/nonrepresentable differences
// return NaN. This model does not cover boundary birth, crossing surfaces or changing contrast.
double filteredBoundaryInteraction(double a0, double a1, double b0, double b1,
        double sigma) noexcept;

} // namespace filament::manymesh::details

#endif // MANYMESH_FILTEREDBOUNDARYERROR_H

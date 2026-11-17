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

#include "../../../libs/manymesh/src/DiscreteFilterEnergy.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>

using namespace filament::manymesh::details;
using Clock = std::chrono::steady_clock;

int main(int argc, char** argv) {
    if (argc != 2) { std::cerr << "usage: mm_filter_energy_bench raster-deltas.txt\n"; return EXIT_FAILURE; }
    std::ifstream input(argv[1]);
    int width, height, scale;
    double sigma;
    size_t count;
    if (!(input >> width >> height >> scale >> sigma >> count) || count > 100000) { return EXIT_FAILURE; }
    auto const start = Clock::now();
    DiscreteFilterEnergy accumulator(width, height, scale, sigma);
    if (!accumulator.valid()) { return EXIT_FAILURE; }
    double const setup = std::chrono::duration<double>(Clock::now()-start).count();
    std::cout << std::setprecision(17) << "{\"setupSeconds\":" << setup
              << ",\"persistentBytes\":" << accumulator.persistentBytes()
              << ",\"scope\":\"native scoring of pre-extracted deltas, not end-to-end\",\"cases\":[\n";
    volatile double checksum = 0.0;
    for (size_t c = 0; c < count; ++c) {
        int frame, id;
        size_t samples;
        double reference, extraction;
        if (!(input >> frame >> id >> samples >> reference >> extraction) || samples > 1000000) {
            return EXIT_FAILURE;
        }
        std::vector<RasterDelta> delta(samples);
        for (auto& e: delta) {
            if (!(input >> e.x >> e.y >> e.value[0] >> e.value[1])) { return EXIT_FAILURE; }
        }
        // Cap quadratic test cost. Splat remains the production-shaped sparse baseline.
        bool const gramEnabled = samples <= 2048;
        double const splat = accumulator.evaluateSplat(delta);
        double const gram = gramEnabled ? accumulator.evaluateGram(delta) : splat;
        double const tolerance = 1e-11 * std::max(1.0, reference);
        if (!std::isfinite(splat) || std::abs(splat-reference) > tolerance ||
                !std::isfinite(gram) || std::abs(gram-reference) > tolerance) {
            std::cerr << "reference mismatch: " << frame << '/' << id << ' ' << splat << ' '
                      << gram << ' ' << reference << '\n';
            return EXIT_FAILURE;
        }
        std::vector<double> splatTimes, gramTimes;
        int const repetitions = samples < 128 ? 100 : 10;
        for (int trial = 0; trial < 6; ++trial) {
            for (int order = 0; order < 2; ++order) {
                bool const runGram = ((order+trial)%2) != 0;
                if (runGram && !gramEnabled) { continue; }
                auto const begin = Clock::now();
                double sum = 0.0;
                for (int repeat = 0; repeat < repetitions; ++repeat) {
                    sum += runGram ? accumulator.evaluateGram(delta) : accumulator.evaluateSplat(delta);
                }
                checksum = checksum + sum;
                double const elapsed = std::chrono::duration<double>(Clock::now()-begin).count()/repetitions;
                (runGram ? gramTimes : splatTimes).push_back(elapsed);
            }
        }
        std::sort(splatTimes.begin(), splatTimes.end());
        std::sort(gramTimes.begin(), gramTimes.end());
        double const ts = (splatTimes[2]+splatTimes[3])*0.5;
        if (c) { std::cout << ",\n"; }
        std::cout << "{\"frame\":" << frame << ",\"id\":" << id << ",\"samples\":" << samples
                  << ",\"referenceError\":" << reference << ",\"splatError\":" << splat
                  << ",\"gramError\":" << gram << ",\"splatSeconds\":" << ts
                  << ",\"gramSeconds\":";
        if (gramEnabled) { std::cout << (gramTimes[2]+gramTimes[3])*0.5; } else { std::cout << "null"; }
        std::cout << ",\"pythonExtractionSeconds\":" << extraction << '}';
    }
    std::cout << "\n],\"checksum\":" << checksum << "}\n";
    return EXIT_SUCCESS;
}

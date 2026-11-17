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

#include "../../../libs/manymesh/src/FilteredBoundaryError.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <limits>
#include <string>
#include <vector>

using namespace filament::manymesh::details;

namespace {
constexpr int WIDTH = 160;
constexpr int HEIGHT = 160;
constexpr int SECTIONS = 41;
using Clock = std::chrono::steady_clock;
struct Section { double y; double left; double right; };
using Strip = std::vector<Section>;

Section sample(Strip const& strip, double y, int omitted = -1) {
    int a = 0;
    while (a + 1 < int(strip.size()) && strip[a + 1].y <= y) {
        ++a;
    }
    if (a == omitted) { --a; }
    int b = a + 1;
    if (b == omitted) { ++b; }
    if (b >= int(strip.size())) { return strip.back(); }
    double const t = (y - strip[a].y) / (strip[b].y - strip[a].y);
    return { y, strip[a].left * (1.0 - t) + strip[b].left * t,
            strip[a].right * (1.0 - t) + strip[b].right * t };
}

Strip makeStrip(int scene, double phase) {
    Strip strip;
    for (int i = 0; i < SECTIONS; ++i) {
        double const t = double(i) / (SECTIONS - 1);
        double const y = 8.0 + 144.0 * t;
        double const center = 80.0 + 14.0 * std::sin(6.0 * t + phase) +
                (0.15 + 0.07 * scene) * std::sin(59.0 * t + scene);
        double const width = 0.3 + (0.3 + 0.4 * scene) *
                (1.1 + std::sin(13.0 * t + phase)) + 0.1 * std::cos(41.0 * t);
        strip.push_back({ y, center - width * 0.5, center + width * 0.5 });
    }
    return strip;
}

// Orthographic strip rasterization: exact Gaussian filtering along x, sampled along y, then
// normalized finite Gaussian convolution along y. It is a controlled CPU reference, NOT Filament
// or a hardware GPU baseline. Pixel values are point samples of the filtered coverage function.
std::vector<double> render(Strip const& strip, int omitted, double sigma) {
    std::vector<double> image(WIDTH * HEIGHT, 0.0);
    double const denominator = sigma * std::sqrt(2.0);
    for (int y = 0; y < HEIGHT; ++y) {
        double const py = y + 0.5;
        if (py < strip.front().y || py > strip.back().y) { continue; }
        Section const s = sample(strip, py, omitted);
        for (int x = 0; x < WIDTH; ++x) {
            double const px = x + 0.5;
            image[y * WIDTH + x] = 0.5 * (std::erfc((s.left - px) / denominator) -
                    std::erfc((s.right - px) / denominator));
        }
    }
    std::vector<double> filtered(image.size(), 0.0);
    int const radius = int(std::ceil(4.0 * sigma));
    std::vector<double> weights(2 * radius + 1);
    double total = 0.0;
    for (int k = -radius; k <= radius; ++k) {
        double const w = std::exp(-0.5 * k * k / (sigma * sigma));
        weights[k + radius] = w;
        total += w;
    }
    for (int y = 0; y < HEIGHT; ++y) {
        for (int k = -radius; k <= radius; ++k) {
            if (y + k < 0 || y + k >= HEIGHT) { continue; }
            double const w = weights[k + radius] / total;
            for (int x = 0; x < WIDTH; ++x) {
                filtered[y * WIDTH + x] += w * image[(y + k) * WIDTH + x];
            }
        }
    }
    return filtered;
}

// Stronger comparison: rasterize only the changed patch and filter the image residual.
// Gaussian filtering is linear, so this matches full rendering up to the explicit 10-sigma x tail.
double patchError(Strip const& strip, int omitted, double sigma) {
    int const radius = int(std::ceil(4.0 * sigma));
    int const y0 = std::max(0, int(std::floor(strip[omitted - 1].y)) - radius - 1);
    int const y1 = std::min(HEIGHT, int(std::ceil(strip[omitted + 1].y)) + radius + 1);
    double left = WIDTH, right = 0.0;
    for (int i = omitted - 1; i <= omitted + 1; ++i) {
        left = std::min(left, strip[i].left);
        right = std::max(right, strip[i].right);
    }
    int const x0 = std::max(0, int(std::floor(left - 10.0 * sigma)));
    int const x1 = std::min(WIDTH, int(std::ceil(right + 10.0 * sigma)));
    int const width = x1 - x0;
    std::vector<double> residual(width * (y1 - y0), 0.0);
    double const denominator = sigma * std::sqrt(2.0);
    for (int y = y0; y < y1; ++y) {
        double const py = y + 0.5;
        if (py < strip[omitted - 1].y || py > strip[omitted + 1].y) { continue; }
        auto const a = sample(strip, py);
        auto const b = sample(strip, py, omitted);
        for (int x = x0; x < x1; ++x) {
            double const px = x + 0.5;
            residual[(y - y0) * width + x - x0] = 0.5 *
                    (std::erfc((b.left - px) / denominator) -
                     std::erfc((b.right - px) / denominator) -
                     std::erfc((a.left - px) / denominator) +
                     std::erfc((a.right - px) / denominator));
        }
    }
    std::vector<double> weights(2 * radius + 1);
    double total = 0.0;
    for (int k = -radius; k <= radius; ++k) {
        weights[k + radius] = std::exp(-0.5 * k * k / (sigma * sigma));
        total += weights[k + radius];
    }
    double loss = 0.0;
    for (int y = y0; y < y1; ++y) {
        for (int x = 0; x < width; ++x) {
            double value = 0.0;
            for (int k = -radius; k <= radius; ++k) {
                if (y + k < y0 || y + k >= y1) { continue; }
                value += weights[k + radius] / total *
                        residual[(y + k - y0) * width + x];
            }
            loss += value * value;
        }
    }
    return loss;
}

double imageError(std::vector<double> const& image, std::vector<double> const& reference) {
    double sum = 0.0;
    for (size_t i = 0; i < image.size(); ++i) {
        double const d = image[i] - reference[i];
        sum += d * d;
    }
    return sum;
}

struct Scores { double displacement = 0.0; double independent = 0.0; double coupled = 0.0; };
Scores predict(Strip const& strip, int omitted, double sigma) {
    Scores scores;
    // No image construction and no loop over horizontal pixels. Only affected scanlines.
    for (int y = 0; y < HEIGHT; ++y) {
        double const py = y + 0.5;
        if (py < strip[omitted - 1].y || py > strip[omitted + 1].y) { continue; }
        Section const before = sample(strip, py);
        Section const after = sample(strip, py, omitted);
        double const dl = after.left - before.left;
        double const dr = after.right - before.right;
        double const independent = filteredBoundaryLoss(dl, sigma).value +
                filteredBoundaryLoss(dr, sigma).value;
        double const cross = filteredBoundaryInteraction(before.left, after.left,
                before.right, after.right, sigma);
        scores.displacement += dl * dl + dr * dr;
        scores.independent += independent;
        scores.coupled += independent - 2.0 * cross;
    }
    return scores;
}

double predictFilteredRows(Strip const& strip, int omitted, double sigma) {
    struct Row { int y; Section before; Section after; };
    std::vector<Row> rows;
    for (int y = 0; y < HEIGHT; ++y) {
        double const py = y + 0.5;
        if (py >= strip[omitted - 1].y && py <= strip[omitted + 1].y) {
            rows.push_back({ y, sample(strip, py), sample(strip, py, omitted) });
        }
    }
    int const radius = int(std::ceil(4.0 * sigma));
    std::vector<double> weights(2 * radius + 1);
    double total = 0.0;
    for (int k = -radius; k <= radius; ++k) {
        weights[k + radius] = std::exp(-0.5 * k * k / (sigma * sigma));
        total += weights[k + radius];
    }
    for (double& weight: weights) { weight /= total; }
    double loss = 0.0;
    for (size_t i = 0; i < rows.size(); ++i) {
        auto const& a = rows[i];
        for (size_t j = i; j < rows.size(); ++j) {
            auto const& b = rows[j];
            if (b.y - a.y > 2 * radius) { break; }
            double coefficient = 0.0;
            for (int y = std::max(0, b.y - radius);
                    y <= std::min(HEIGHT - 1, a.y + radius); ++y) {
                coefficient += weights[y - a.y + radius] * weights[y - b.y + radius];
            }
            double const inner = filteredBoundaryInteraction(a.before.left, a.after.left,
                    b.before.left, b.after.left, sigma) -
                    filteredBoundaryInteraction(a.before.left, a.after.left,
                            b.before.right, b.after.right, sigma) -
                    filteredBoundaryInteraction(a.before.right, a.after.right,
                            b.before.left, b.after.left, sigma) +
                    filteredBoundaryInteraction(a.before.right, a.after.right,
                            b.before.right, b.after.right, sigma);
            loss += (i == j ? coefficient : 2.0 * coefficient) * inner;
        }
    }
    return loss;
}

// Deterministic Fourier quadrature of the residual, shared across scanlines. Parseval turns
// cross-boundary and cross-row coupling into sums of squared complex amplitudes. This is a
// continuous-x surrogate; horizontal pixel sampling can still disagree at small sigma.
double predictSpectrum(Strip const& strip, int omitted, double sigma, int frequencies) {
    int const radius = int(std::ceil(4.0 * sigma));
    int const y0 = std::max(0, int(std::floor(strip[omitted - 1].y)) - radius - 1);
    int const y1 = std::min(HEIGHT, int(std::ceil(strip[omitted + 1].y)) + radius + 1);
    std::vector<double> weights(2 * radius + 1);
    double total = 0.0;
    for (int k = -radius; k <= radius; ++k) {
        weights[k + radius] = std::exp(-0.5 * k * k / (sigma * sigma));
        total += weights[k + radius];
    }
    for (double& weight: weights) { weight /= total; }
    double const pi = std::acos(-1.0);
    double const step = 5.0 / (sigma * frequencies);
    double const origin = strip[omitted].left;
    std::vector<std::complex<double>> rows(y1 - y0);
    double loss = 0.0;
    for (int f = 0; f < frequencies; ++f) {
        double const omega = (f + 0.5) * step;
        auto motion = [omega, origin](double before, double after) {
            double const d = after - before;
            double const phase = -omega * ((before - origin) + 0.5 * d);
            double const amplitude = 2.0 * std::sin(0.5 * omega * d) / omega;
            return amplitude * std::complex<double>(std::cos(phase), std::sin(phase));
        };
        std::fill(rows.begin(), rows.end(), std::complex<double>(0.0, 0.0));
        for (int y = y0; y < y1; ++y) {
            double const py = y + 0.5;
            if (py < strip[omitted - 1].y || py > strip[omitted + 1].y) { continue; }
            auto const before = sample(strip, py);
            auto const after = sample(strip, py, omitted);
            rows[y - y0] = motion(before.left, after.left) -
                    motion(before.right, after.right);
        }
        double energy = 0.0;
        for (int y = y0; y < y1; ++y) {
            std::complex<double> value(0.0, 0.0);
            for (int k = -radius; k <= radius; ++k) {
                if (y + k < y0 || y + k >= y1) { continue; }
                value += weights[k + radius] * rows[y + k - y0];
            }
            energy += std::norm(value);
        }
        loss += step / pi * std::exp(-sigma * sigma * omega * omega) * energy;
    }
    return loss;
}

void writeImage(std::string const& path, std::vector<double> const& image) {
    std::ofstream out(path, std::ios::binary);
    if (!out) {
        std::fprintf(stderr, "cannot write image: %s\n", path.c_str());
        std::exit(EXIT_FAILURE);
    }
    out << "P5\n" << WIDTH << " " << HEIGHT << "\n255\n";
    for (double value: image) {
        unsigned char const byte = static_cast<unsigned char>(
                std::lround(255.0 * std::clamp(value, 0.0, 1.0)));
        out.write(reinterpret_cast<char const*>(&byte), 1);
    }
}

void writeMesh(std::string const& path, Strip const& strip, int omitted) {
    std::ofstream out(path);
    if (!out) {
        std::fprintf(stderr, "cannot write mesh: %s\n", path.c_str());
        std::exit(EXIT_FAILURE);
    }
    out << std::setprecision(17);
    int count = 0;
    for (int i = 0; i < int(strip.size()); ++i) {
        if (i == omitted) { continue; }
        out << "v " << strip[i].left << " " << strip[i].y << " 0\n";
        out << "v " << strip[i].right << " " << strip[i].y << " 0\n";
        ++count;
    }
    for (int i = 0; i + 1 < count; ++i) {
        int const a = 2 * i + 1;
        out << "f " << a << " " << a + 1 << " " << a + 2 << "\n";
        out << "f " << a + 1 << " " << a + 3 << " " << a + 2 << "\n";
    }
}
// A residual vector, not a scalar operation cost. Applying an operation updates r <- r + delta;
// its cumulative image loss changes by 2<r,delta> + ||delta||^2. Inverse operations negate delta
// only while the projection/filter state is unchanged. Camera changes rebuild the reference.
struct ResidualPatch {
    int firstRow;
    int rowCount;
    int frequencies;
    std::vector<std::complex<double>> values;
};

ResidualPatch spectralDelta(Strip const& before, Strip const& after, double lowY, double highY,
        double sigma, int frequencies) {
    int const radius = int(std::ceil(4.0 * sigma));
    int const y0 = std::max(0, int(std::floor(lowY)) - radius - 1);
    int const y1 = std::min(HEIGHT, int(std::ceil(highY)) + radius + 1);
    ResidualPatch patch{ y0, y1 - y0, frequencies, {} };
    patch.values.resize((y1 - y0) * frequencies);
    std::vector<double> weights(2 * radius + 1);
    double total = 0.0;
    for (int k = -radius; k <= radius; ++k) {
        weights[k + radius] = std::exp(-0.5 * k * k / (sigma * sigma));
        total += weights[k + radius];
    }
    for (double& weight: weights) { weight /= total; }
    double const pi = std::acos(-1.0);
    double const step = 5.0 / (sigma * frequencies);
    for (int y = y0; y < y1; ++y) {
        double const py = y + 0.5;
        if (py < lowY || py > highY) { continue; }
        auto const a = sample(before, py);
        auto const b = sample(after, py);
        for (int f = 0; f < frequencies; ++f) {
            double const omega = (f + 0.5) * step;
            auto motion = [omega](double from, double to) {
                double const phase = -omega * (0.5 * (from + to) - WIDTH * 0.5);
                return (2.0 * std::sin(0.5 * omega * (to - from)) / omega) *
                        std::complex<double>(std::cos(phase), std::sin(phase));
            };
            auto const amplitude = (motion(a.left, b.left) - motion(a.right, b.right)) *
                    std::sqrt(step / pi) * std::exp(-0.5 * sigma * sigma * omega * omega);
            for (int k = -radius; k <= radius; ++k) {
                int const outputRow = y + k;
                if (outputRow >= y0 && outputRow < y1) {
                    patch.values[(outputRow - y0) * frequencies + f] +=
                            weights[k + radius] * amplitude;
                }
            }
        }
    }
    return patch;
}

double residualChange(std::vector<std::complex<double>> const& residual,
        ResidualPatch const& delta) {
    double result = 0.0;
    for (int y = 0; y < delta.rowCount; ++y) {
        for (int f = 0; f < delta.frequencies; ++f) {
            auto const d = delta.values[y * delta.frequencies + f];
            auto const r = residual[(y + delta.firstRow) * delta.frequencies + f];
            result += 2.0 * std::real(std::conj(r) * d) + std::norm(d);
        }
    }
    return result;
}

void applyResidual(std::vector<std::complex<double>>& residual, ResidualPatch const& delta,
        double sign = 1.0) {
    for (int y = 0; y < delta.rowCount; ++y) {
        for (int f = 0; f < delta.frequencies; ++f) {
            residual[(y + delta.firstRow) * delta.frequencies + f] +=
                    sign * delta.values[y * delta.frequencies + f];
        }
    }
}

Strip subset(Strip const& original, std::vector<int> const& ids) {
    Strip result;
    for (int id: ids) { result.push_back(original[id]); }
    return result;
}

int runDynamic(std::string const& output) {
    // Controlled reversible section removal, not a general-purpose mesh edge-collapse engine.
    // Each removal deletes two boundary vertices and two triangles, each insertion restores them.
    // Three policies see identical camera/deformation and budgets but maintain their own geometry.
    int const targets[] = { 31, 21, 13, 21, 31, 13 };
    bool first = true;
    std::printf("{\"scope\":\"reversible synthetic strip; no general mesh topology claim\","
                "\"frames\":[\n");
    for (int scene = 0; scene < 4; ++scene) {
        for (int policy = 0; policy < 3; ++policy) {
            std::vector<int> ids;
            for (int i = 0; i < SECTIONS; ++i) { ids.push_back(i); }
            for (int frame = 0; frame < 6; ++frame) {
                Strip const original = makeStrip(scene, 0.15 * frame);
                Strip current = subset(original, ids);
                double const sigma = 0.9;
                int const frequencies = 16;
                auto const begin = Clock::now();
                std::vector<std::complex<double>> residual(HEIGHT * frequencies);
                applyResidual(residual, spectralDelta(original, current, original.front().y,
                        original.back().y, sigma, frequencies));
                int operations = 0;
                size_t candidateCount = 0;
                double maxUndoDifference = 0.0;
                while (int(ids.size()) != targets[frame]) {
                    bool const removing = int(ids.size()) > targets[frame];
                    double best = std::numeric_limits<double>::infinity();
                    int bestId = -1;
                    Strip bestMesh;
                    std::vector<int> bestIds;
                    ResidualPatch bestDelta{};
                    for (int id = 1; id + 1 < SECTIONS; ++id) {
                        auto const position = std::lower_bound(ids.begin(), ids.end(), id);
                        bool const present = position != ids.end() && *position == id;
                        if (present != removing) { continue; }
                        std::vector<int> candidateIds = ids;
                        size_t const index = size_t(position - ids.begin());
                        double lowY, highY;
                        if (removing) {
                            lowY = original[ids[index - 1]].y;
                            highY = original[ids[index + 1]].y;
                            candidateIds.erase(candidateIds.begin() + index);
                        } else {
                            lowY = original[ids[index - 1]].y;
                            highY = original[ids[index]].y;
                            candidateIds.insert(candidateIds.begin() + index, id);
                        }
                        Strip candidate = subset(original, candidateIds);
                        auto delta = spectralDelta(current, candidate, lowY, highY,
                                sigma, frequencies);
                        double score = 0.0;
                        if (policy == 0) {
                            // Cumulative squared boundary displacement from the ORIGINAL mesh.
                            for (int y = 8; y < 152; ++y) {
                                auto const a = sample(original, y + 0.5);
                                auto const b = sample(candidate, y + 0.5);
                                score += (a.left - b.left) * (a.left - b.left) +
                                        (a.right - b.right) * (a.right - b.right);
                            }
                        } else if (policy == 1) {
                            // Deliberate ablation: ignore the residual already introduced.
                            for (auto const& value: delta.values) { score += std::norm(value); }
                            if (!removing) { score = -score; }
                        } else {
                            score = residualChange(residual, delta);
                        }
                        ++candidateCount;
                        if (score < best) {
                            best = score;
                            bestId = id;
                            bestMesh = std::move(candidate);
                            bestIds = std::move(candidateIds);
                            bestDelta = std::move(delta);
                        }
                    }
                    if (bestId < 0) { return EXIT_FAILURE; }
                    // Exercise exact local undo before committing; no graph/state mutation hidden.
                    auto const previous = residual;
                    applyResidual(residual, bestDelta);
                    applyResidual(residual, bestDelta, -1.0);
                    for (size_t i = 0; i < residual.size(); ++i) {
                        maxUndoDifference = std::max(maxUndoDifference,
                                std::abs(residual[i] - previous[i]));
                    }
                    applyResidual(residual, bestDelta);
                    current = std::move(bestMesh);
                    ids = std::move(bestIds);
                    ++operations;
                }
                double const updateUs = std::chrono::duration<double, std::micro>(
                        Clock::now() - begin).count();
                // Rebuild independently to catch invalid support windows or residual composition.
                std::vector<std::complex<double>> rebuilt(HEIGHT * frequencies);
                applyResidual(rebuilt, spectralDelta(original, current, original.front().y,
                        original.back().y, sigma, frequencies));
                double maxRebuildDifference = 0.0, predicted = 0.0;
                for (size_t i = 0; i < residual.size(); ++i) {
                    maxRebuildDifference = std::max(maxRebuildDifference,
                            std::abs(residual[i] - rebuilt[i]));
                    predicted += std::norm(residual[i]);
                }
                if (maxRebuildDifference > 1e-9 || maxUndoDifference > 1e-12) {
                    std::fprintf(stderr, "residual composition mismatch\n");
                    return EXIT_FAILURE;
                }
                auto const image = render(current, -1, sigma);
                double const actual = imageError(image, render(original, -1, sigma));
                if (!first) { std::printf(",\n"); }
                first = false;
                std::printf("{\"scene\":%d,\"policy\":%d,\"frame\":%d,\"triangles\":%zu,"
                            "\"operations\":%d,\"candidates\":%zu,\"updateUs\":%.6f,"
                            "\"predictedError\":%.12g,\"actualError\":%.12g,"
                            "\"maxRebuildDifference\":%.9g,\"maxUndoDifference\":%.9g}",
                        scene, policy, frame, 2 * (current.size() - 1), operations, candidateCount,
                        updateUs, predicted, actual, maxRebuildDifference, maxUndoDifference);
                if (!output.empty()) {
                    std::string const stem = output + "/dynamic-" + std::to_string(scene) + "-" +
                            std::to_string(policy) + "-" + std::to_string(frame);
                    writeImage(stem + ".pgm", image);
                    writeMesh(stem + ".obj", current, -1);
                    if (policy == 0) {
                        writeImage(output + "/reference-" + std::to_string(scene) + "-" +
                                std::to_string(frame) + ".pgm", render(original, -1, sigma));
                    }
                }
            }
        }
    }
    std::printf("\n]}\n");
    return EXIT_SUCCESS;
}
} // namespace

int main(int argc, char** argv) {
    // Optional existing directory for evidence. Does not create directories or overwrite sources.
    bool const dynamic = argc > 1 && std::string(argv[1]) == "--dynamic";
    std::string const output = dynamic ? (argc > 2 ? argv[2] : "") : (argc > 1 ? argv[1] : "");
    if (dynamic) { return runDynamic(output); }
    std::printf("{\"scope\":\"synthetic orthographic strips; CPU filtered raster reference\","
                "\"baseTriangles\":80,\"candidateTriangles\":78,\"cases\":[\n");
    bool first = true;
    for (int scene = 0; scene < 6; ++scene) {
        for (int frame = 0; frame < 4; ++frame) {
            double const sigma = (frame & 1) ? 0.9 : 0.5;
            Strip const strip = makeStrip(scene, 0.4 * frame);
            auto const reference = render(strip, -1, sigma);
            std::vector<Scores> scores(SECTIONS - 2);
            std::vector<double> truth(SECTIONS - 2);
            auto const begin = Clock::now();
            // Repeated predictor runs amortize timer overhead; all work remains observable.
            double checksum = 0.0;
            constexpr int REPEATS = 40;
            for (int repeat = 0; repeat < REPEATS; ++repeat) {
                for (int i = 1; i + 1 < SECTIONS; ++i) {
                    scores[i - 1] = predict(strip, i, sigma);
                    checksum += scores[i - 1].coupled;
                }
            }
            double const predictUs = std::chrono::duration<double, std::micro>(
                    Clock::now() - begin).count() / REPEATS;
            auto const rasterBegin = Clock::now();
            for (int i = 1; i + 1 < SECTIONS; ++i) {
                truth[i - 1] = imageError(render(strip, i, sigma), reference);
            }
            double const rasterUs = std::chrono::duration<double, std::micro>(
                    Clock::now() - rasterBegin).count();
            auto const patchBegin = Clock::now();
            double patchChecksum = 0.0;
            double maxPatchDifference = 0.0;
            for (int repeat = 0; repeat < REPEATS; ++repeat) {
                for (int i = 1; i + 1 < SECTIONS; ++i) {
                    double const error = patchError(strip, i, sigma);
                    patchChecksum += error;
                    maxPatchDifference = std::max(maxPatchDifference,
                            std::abs(error - truth[i - 1]));
                }
            }
            double const patchUs = std::chrono::duration<double, std::micro>(
                    Clock::now() - patchBegin).count() / REPEATS;
            if (maxPatchDifference > 1e-10) {
                std::fprintf(stderr, "patch reference mismatch: %.17g\n", maxPatchDifference);
                return EXIT_FAILURE;
            }
            std::vector<double> rowScores(SECTIONS - 2);
            auto const rowBegin = Clock::now();
            double rowChecksum = 0.0;
            for (int repeat = 0; repeat < REPEATS; ++repeat) {
                for (int i = 1; i + 1 < SECTIONS; ++i) {
                    rowScores[i - 1] = predictFilteredRows(strip, i, sigma);
                    rowChecksum += rowScores[i - 1];
                }
            }
            double const rowUs = std::chrono::duration<double, std::micro>(
                    Clock::now() - rowBegin).count() / REPEATS;
            int geometric = 0, independent = 0, coupled = 0, oracle = 0, rowChoice = 0;
            double rowAbsoluteError = 0.0;
            double absoluteError = 0.0, truthSum = 0.0;
            for (int i = 0; i < int(scores.size()); ++i) {
                if (scores[i].displacement < scores[geometric].displacement) { geometric = i; }
                if (scores[i].independent < scores[independent].independent) { independent = i; }
                if (scores[i].coupled < scores[coupled].coupled) { coupled = i; }
                if (truth[i] < truth[oracle]) { oracle = i; }
                absoluteError += std::abs(scores[i].coupled - truth[i]);
                truthSum += truth[i];
                rowAbsoluteError += std::abs(rowScores[i] - truth[i]);
                if (rowScores[i] < rowScores[rowChoice]) { rowChoice = i; }
            }
            struct SpectrumResult {
                int frequencies;
                double microseconds;
                double relativeL1;
                double actualError;
                double checksum;
                int choice;
            };
            std::vector<SpectrumResult> spectrumResults;
            for (int frequencies: { 4, 8, 16, 32 }) {
                std::vector<double> estimates(SECTIONS - 2);
                auto const start = Clock::now();
                double spectralChecksum = 0.0;
                for (int repeat = 0; repeat < REPEATS; ++repeat) {
                    for (int i = 1; i + 1 < SECTIONS; ++i) {
                        estimates[i - 1] = predictSpectrum(strip, i, sigma, frequencies);
                        spectralChecksum += estimates[i - 1];
                    }
                }
                double const microseconds = std::chrono::duration<double, std::micro>(
                        Clock::now() - start).count() / REPEATS;
                int choice = 0;
                double error = 0.0;
                for (int i = 0; i < int(estimates.size()); ++i) {
                    if (estimates[i] < estimates[choice]) { choice = i; }
                    error += std::abs(estimates[i] - truth[i]);
                }
                spectrumResults.push_back({ frequencies, microseconds,
                        error / std::max(truthSum, 1e-30), truth[choice], spectralChecksum, choice + 1 });
            }
            if (!first) { std::printf(",\n"); }
            first = false;
            std::printf("{\"scene\":%d,\"frame\":%d,\"sigma\":%.1f,\"candidates\":%zu,"
                        "\"predictUs\":%.6f,\"rasterUs\":%.6f,\"checksum\":%.9g,"
                        "\"patchUs\":%.6f,\"patchChecksum\":%.9g,\"maxPatchDifference\":%.9g,"
                        "\"geometricError\":%.12g,\"independentError\":%.12g,"
                        "\"coupledError\":%.12g,\"oracleError\":%.12g,"
                        "\"relativePredictionL1\":%.9g,\"coupledChoice\":%d,\"oracleChoice\":%d,"
                        "\"rowUs\":%.6f,\"rowChecksum\":%.9g,\"rowError\":%.12g,"
                        "\"rowRelativePredictionL1\":%.9g,\"rowChoice\":%d,\"spectrum\":[",
                    scene, frame, sigma, scores.size(), predictUs, rasterUs, checksum,
                    patchUs, patchChecksum, maxPatchDifference,
                    truth[geometric], truth[independent], truth[coupled], truth[oracle],
                    absoluteError / std::max(truthSum, 1e-30), coupled + 1, oracle + 1,
                    rowUs, rowChecksum, truth[rowChoice],
                    rowAbsoluteError / std::max(truthSum, 1e-30), rowChoice + 1);
            for (size_t i = 0; i < spectrumResults.size(); ++i) {
                auto const& s = spectrumResults[i];
                std::printf("%s{\"frequencies\":%d,\"microseconds\":%.6f,\"relativeL1\":%.9g,"
                            "\"actualError\":%.12g,\"checksum\":%.9g,\"choice\":%d}",
                        i ? "," : "", s.frequencies, s.microseconds, s.relativeL1,
                        s.actualError, s.checksum, s.choice);
            }
            std::printf("]}");
            if (!output.empty()) {
                std::string const stem = output + "/strip-" + std::to_string(scene) + "-" +
                        std::to_string(frame);
                writeImage(stem + "-reference.pgm", reference);
                writeImage(stem + "-geometric.pgm", render(strip, geometric + 1, sigma));
                writeImage(stem + "-coupled.pgm", render(strip, coupled + 1, sigma));
                writeMesh(stem + "-reference.obj", strip, -1);
                writeMesh(stem + "-coupled.obj", strip, coupled + 1);
            }
        }
    }
    std::printf("\n]}\n");
    return EXIT_SUCCESS;
}

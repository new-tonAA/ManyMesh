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

#ifndef TNT_MANYMESH_PARALLEL_H
#define TNT_MANYMESH_PARALLEL_H

#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <thread>
#include <vector>

namespace filament {
namespace manymesh {
namespace detail {

/**
 * Minimal fork-join loop for independent build work.
 *
 * The caller must give every index a disjoint output slot. There is intentionally no exception
 * propagation and no nested parallelism: this is used by offline/editor-side DAG construction,
 * not by the render thread.
 */
template<typename Function>
void parallelFor(size_t count, Function&& function) {
    if (count == 0) {
        return;
    }
    unsigned hardware = std::thread::hardware_concurrency();
    if (hardware == 0) {
        hardware = 1;
    }
    size_t workers = std::min<size_t>(hardware, count);
    // Offline tools and the determinism test can pin the worker count. A value of 1 must take
    // the exact same serial path as a single-core machine.
    if (char const* configured = std::getenv("MANYMESH_BUILD_THREADS")) {
        char* end = nullptr;
        unsigned long const value = std::strtoul(configured, &end, 10);
        if (end != configured && value > 0) {
            workers = std::min<size_t>(size_t(value), count);
        }
    }
    if (workers <= 1) {
        for (size_t i = 0; i < count; ++i) {
            function(i);
        }
        return;
    }

    std::atomic<size_t> next{ 0 };
    std::vector<std::thread> threads;
    threads.reserve(workers);
    for (size_t worker = 0; worker < workers; ++worker) {
        threads.emplace_back([&] {
            for (;;) {
                size_t const i = next.fetch_add(1, std::memory_order_relaxed);
                if (i >= count) {
                    break;
                }
                function(i);
            }
        });
    }
    for (std::thread& thread: threads) {
        thread.join();
    }
}

} // namespace detail
} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_PARALLEL_H

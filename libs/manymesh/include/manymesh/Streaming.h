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

#ifndef TNT_MANYMESH_STREAMING_H
#define TNT_MANYMESH_STREAMING_H

#include <manymesh/LodGraph.h>

#include <fstream>
#include <list>
#include <map>
#include <string>
#include <vector>

#include <stddef.h>
#include <stdint.h>

namespace filament {
namespace manymesh {

/**
 * Serializes a LodGraph to a self-contained little-endian binary blob.
 *
 * The layout is deliberately page friendly: a fixed header, the root/leaf arrays, a table of
 * per-node byte offsets, and then one contiguous record per node. A runtime can therefore read
 * only the nodes a view selected instead of materializing the whole hierarchy.
 */
std::vector<uint8_t> serializeLodGraph(LodGraph const& graph);

bool writeLodGraphFile(LodGraph const& graph, char const* path);

bool deserializeLodGraph(std::vector<uint8_t> const& blob, LodGraph* graph);

struct LodStreamingPage {
    uint32_t firstNode = 0;
    uint32_t nodeCount = 0;
    uint64_t byteOffset = 0;
    uint64_t byteCount = 0;
};

std::vector<LodStreamingPage> planLodStreamingPages(std::vector<uint8_t> const& blob,
        size_t maxPageBytes);

/**
 * Read-only view over a serialized graph that loads one node at a time.
 *
 * This is the runtime-facing half of the streaming contract: a renderer can keep the blob in a
 * file mapping or chunk source and call readNode/readPage for the current selection.
 */
class StreamingLodGraph {
public:
    explicit StreamingLodGraph(std::vector<uint8_t> blob);

    //! Opens a serialized graph and keeps only the header and offset table in memory. Node
    //! records are read on demand, so a multi-gigabyte hierarchy never has to be resident.
    explicit StreamingLodGraph(std::string const& path);

    bool valid() const noexcept { return mValid; }
    bool fileBacked() const noexcept { return mFile.is_open(); }
    uint32_t nodeCount() const noexcept { return mNodeCount; }
    uint32_t levelCount() const noexcept { return mLevelCount; }
    uint64_t baseTriangles() const noexcept { return mBaseTriangles; }
    uint64_t byteSize() const noexcept { return mBlobSize; }
    std::vector<uint32_t> const& roots() const noexcept { return mRoots; }
    std::vector<uint32_t> const& leaves() const noexcept { return mLeaves; }

    bool readNode(uint32_t nodeId, LodGraphNode* node) const;
    bool readPage(LodStreamingPage const& page, std::vector<LodGraphNode>* nodes) const;
    std::vector<LodStreamingPage> planPages(size_t maxPageBytes) const;

private:
    uint64_t nodeOffset(uint32_t nodeId) const;
    bool readRange(uint64_t offset, size_t size, std::vector<uint8_t>* out) const;

    std::vector<uint8_t> mBlob;
    mutable std::ifstream mFile;
    uint64_t mBlobSize = 0;
    std::vector<uint64_t> mOffsets;
    std::vector<uint32_t> mRoots;
    std::vector<uint32_t> mLeaves;
    uint32_t mNodeCount = 0;
    uint32_t mLevelCount = 0;
    uint64_t mBaseTriangles = 0;
    bool mValid = false;
};

/**
 * A byte-budgeted page cache on top of StreamingLodGraph.
 *
 * `prepare` is the per-frame entry point: it loads pages that contain any selected node and
 * evicts least-recently-used pages until the budget is respected. Nodes referenced by the
 * current selection are never evicted in the same call.
 */
class LodStreamingCache {
public:
    LodStreamingCache(StreamingLodGraph const* graph, size_t byteBudget,
            size_t maxPageBytes = 64 * 1024);

    struct Stats {
        size_t residentPages = 0;
        size_t residentBytes = 0;
        uint64_t pageHits = 0;
        uint64_t pageMisses = 0;
        uint64_t evictions = 0;
    };

    bool prepare(LodGraphSelection const& selection);
    LodGraphNode const* find(uint32_t nodeId) const;
    Stats const& stats() const noexcept { return mStats; }

private:
    struct PageEntry {
        LodStreamingPage page;
        std::vector<LodGraphNode> nodes;
    };

    StreamingLodGraph const* mGraph = nullptr;
    size_t mByteBudget = 0;
    size_t mMaxPageBytes = 0;
    std::vector<LodStreamingPage> mPages;
    std::map<uint32_t, PageEntry> mResident;
    std::list<uint32_t> mLru;
    Stats mStats;
};

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_STREAMING_H

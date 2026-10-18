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

#include <deque>
#include <fstream>
#include <functional>
#include <future>
#include <list>
#include <map>
#include <memory>
#include <mutex>
#include <set>
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

/**
 * Decodes the node records of one serialized page from the bytes a transport fetched for it.
 * This is the hook an HTTP/CDN client uses: fetch `page.byteOffset` for `page.byteCount` bytes,
 * then pass the result here without materializing the rest of the graph.
 */
bool decodeLodStreamingPage(std::vector<uint8_t> const& pageBytes, LodStreamingPage const& page,
        std::vector<LodGraphNode>* nodes);

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
    uint32_t vertexCount() const noexcept { return mVertexCount; }
    uint64_t baseTriangles() const noexcept { return mBaseTriangles; }
    uint64_t byteSize() const noexcept { return mBlobSize; }
    std::vector<uint32_t> const& roots() const noexcept { return mRoots; }
    std::vector<uint32_t> const& leaves() const noexcept { return mLeaves; }

    bool readNode(uint32_t nodeId, LodGraphNode* node) const;
    bool readPage(LodStreamingPage const& page, std::vector<LodGraphNode>* nodes) const;
    bool readBytes(uint64_t offset, size_t size, std::vector<uint8_t>* out) const;
    std::vector<LodStreamingPage> planPages(size_t maxPageBytes) const;

private:
    uint64_t nodeOffset(uint32_t nodeId) const;
    bool readRange(uint64_t offset, size_t size, std::vector<uint8_t>* out) const;

    std::vector<uint8_t> mBlob;
    mutable std::ifstream mFile;
    mutable std::mutex mFileMutex;
    uint64_t mBlobSize = 0;
    std::vector<uint64_t> mOffsets;
    std::vector<uint32_t> mRoots;
    std::vector<uint32_t> mLeaves;
    uint32_t mNodeCount = 0;
    uint32_t mLevelCount = 0;
    uint32_t mVertexCount = 0;
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
        uint64_t bytesFetched = 0;
        uint64_t failedFetches = 0;
    };

    bool prepare(LodGraphSelection const& selection);
    bool prepare(LodGraphCut const& cut);
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

/**
 * Asynchronous page prefetch on top of the same page table.
 *
 * Unlike LodStreamingCache, this class never blocks on I/O. `request` schedules the pages a
 * selection needs, `poll` integrates any completed fetches and starts queued work up to
 * `maxConcurrent`, and `find` exposes the pages that are already resident. The fetcher is a
 * callback so the transport is not tied to the local file reader: an HTTP/CDN client can fetch
 * `page.byteOffset` for `page.byteCount` bytes, decode the node records, and hand them back.
 *
 * A caller that needs a frame immediately can keep rendering with the previous resident set
 * while `pending()` is non-zero, then use the new pages once `ready()` becomes true.
 *
 * The fetcher may be called concurrently by up to `maxConcurrent` workers, so a transport that
 * shares a file handle or connection must serialize that access itself.
 */
class AsyncLodStreamingCache {
public:
    using PageFetcher = std::function<bool(LodStreamingPage const&, std::vector<LodGraphNode>*)>;
    using ByteRangeFetcher =
            std::function<bool(uint64_t offset, size_t size, std::vector<uint8_t>* bytes)>;

    AsyncLodStreamingCache(StreamingLodGraph const* graph, PageFetcher fetcher, size_t byteBudget,
            size_t maxPageBytes = 64 * 1024, size_t maxConcurrent = 4);
    AsyncLodStreamingCache(StreamingLodGraph const* graph, ByteRangeFetcher fetcher,
            size_t byteBudget, size_t maxPageBytes = 64 * 1024, size_t maxConcurrent = 4);

    AsyncLodStreamingCache(AsyncLodStreamingCache const&) = delete;
    AsyncLodStreamingCache& operator=(AsyncLodStreamingCache const&) = delete;

    //! Schedules every page referenced by `selection`. Pages already resident are not refetched.
    bool request(LodGraphSelection const& selection);
    //! Runtime variant: schedules only the nodes in a cut, without assembling its index arrays.
    bool request(LodGraphCut const& cut);

    //! Integrates completed fetches and starts queued ones. Returns true when anything arrived.
    bool poll();

    bool ready() const noexcept { return mQueue.empty() && mPending.empty(); }
    size_t pending() const noexcept { return mQueue.size() + mPending.size(); }
    LodGraphNode const* find(uint32_t nodeId) const;
    LodStreamingCache::Stats const& stats() const noexcept { return mStats; }

private:
    struct PageResult {
        uint32_t pageId = 0;
        LodStreamingPage page;
        std::vector<LodGraphNode> nodes;
        bool ok = false;
    };

    void pump();
    void evict();
    bool requestNodes(std::vector<uint32_t> const& nodes);

    StreamingLodGraph const* mGraph = nullptr;
    PageFetcher mFetcher;
    size_t mByteBudget = 0;
    size_t mMaxPageBytes = 0;
    size_t mMaxConcurrent = 1;
    std::vector<LodStreamingPage> mPages;
    std::map<uint32_t, std::vector<LodGraphNode>> mResident;
    std::list<uint32_t> mLru;
    //! Sorted, deduplicated page ids for the current request; a vector avoids one tree node
    //! allocation per page on every camera change.
    std::vector<uint32_t> mRequired;
    std::set<uint32_t> mRequested;
    std::deque<uint32_t> mQueue;
    std::vector<std::future<PageResult>> mPending;
    LodStreamingCache::Stats mStats;
};

/**
 * Byte-range transport backed by the platform HTTP stack.
 *
 * This is the production transport for `AsyncLodStreamingCache::ByteRangeFetcher`: point it at
 * the serialized `lod_graph.mmb` URL, then pass `asFetcher()` to the cache. Each request sends a
 * `Range: bytes=<offset>-<end>` header and requires a 206 response (a 200 response is accepted
 * only for the first byte of the file, i.e. when the server ignored Range).
 *
 * The implementation uses WinHTTP on Windows. A mobile or custom runtime can inject its own
 * platform HTTP stack through `RangeFetcher`; the cache and page decoder stay unchanged.
 */
class HttpByteRangeFetcher {
public:
    /**
     * Signature of an injected platform transport.
     *
     * The callback must perform one HTTP Range request and return exactly `size` bytes, or return
     * false and set `error`. It may be called concurrently by AsyncLodStreamingCache workers, so
     * implementations sharing a session/connection must serialize that access.
     */
    using RangeFetcher = std::function<bool(uint64_t offset, size_t size,
            std::vector<uint8_t>* bytes, std::string* error)>;

    explicit HttpByteRangeFetcher(std::string url, unsigned timeoutMs = 5000);
    HttpByteRangeFetcher(std::string url, RangeFetcher fetcher, unsigned timeoutMs = 5000);
    ~HttpByteRangeFetcher();

    HttpByteRangeFetcher(HttpByteRangeFetcher const&) = delete;
    HttpByteRangeFetcher& operator=(HttpByteRangeFetcher const&) = delete;

    bool fetch(uint64_t offset, size_t size, std::vector<uint8_t>* bytes);

    bool valid() const noexcept;
    std::string const& url() const noexcept;
    //! Best-effort diagnostic for the last failed fetch. Concurrent fetches may race here.
    std::string const& lastError() const noexcept;

    //! Binds this transport to a cache. The fetcher must not outlive the HttpByteRangeFetcher.
    AsyncLodStreamingCache::ByteRangeFetcher asFetcher();

private:
    struct Impl;
    std::unique_ptr<Impl> mImpl;
};

} // namespace manymesh
} // namespace filament

#endif // TNT_MANYMESH_STREAMING_H

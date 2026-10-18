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

#include <manymesh/Streaming.h>

#include <algorithm>
#include <chrono>
#include <cstring>
#include <iterator>
#include <set>
#include <utility>

namespace filament {
namespace manymesh {

namespace {

constexpr uint32_t MAGIC = 0x474C4D4Du; // "MMLG" in little-endian byte order
// Version 2 appends the topology and attribute statistics gathered by the quality gate.
// The layout still has one fixed-size prefix followed by variable child/index arrays, so a
// runtime can keep reading individual nodes without deserializing the whole graph.
constexpr uint32_t VERSION = 2u;
constexpr size_t NODE_RECORD_SIZE = 184;

template<typename T>
void append(std::vector<uint8_t>* blob, T const& value) {
    size_t const offset = blob->size();
    blob->resize(offset + sizeof(T));
    std::memcpy(blob->data() + offset, &value, sizeof(T));
}

template<typename T>
bool read(std::vector<uint8_t> const& blob, size_t* offset, T* value) {
    if (*offset > blob.size() || blob.size() - *offset < sizeof(T)) {
        return false;
    }
    std::memcpy(value, blob.data() + *offset, sizeof(T));
    *offset += sizeof(T);
    return true;
}

template<typename T>
bool readStream(std::istream& stream, T* value) {
    stream.read(reinterpret_cast<char*>(value), sizeof(T));
    return bool(stream);
}

void patchU64(std::vector<uint8_t>* blob, size_t offset, uint64_t value) {
    std::memcpy(blob->data() + offset, &value, sizeof(value));
}

void writeNode(std::vector<uint8_t>* blob, LodGraphNode const& node) {
    append(blob, node.level);
    append(blob, node.parent);
    append(blob, node.materialId);
    append(blob, node.submeshId);
    append(blob, uint32_t(node.children.size()));
    append(blob, uint32_t(node.indices.size()));
    append(blob, node.baseTriangles);
    append(blob, node.selfError);
    append(blob, node.accumulatedError);
    append(blob, node.bounds.center.x);
    append(blob, node.bounds.center.y);
    append(blob, node.bounds.center.z);
    append(blob, node.bounds.radius);
    append(blob, node.cone.apex.x);
    append(blob, node.cone.apex.y);
    append(blob, node.cone.apex.z);
    append(blob, node.cone.axis.x);
    append(blob, node.cone.axis.y);
    append(blob, node.cone.axis.z);
    append(blob, node.cone.cutoff);
    uint8_t const simplified = node.simplified ? 1 : 0;
    append(blob, simplified);
    append(blob, uint8_t(0));
    append(blob, uint8_t(0));
    append(blob, uint8_t(0));
    append(blob, node.topology.triangles);
    append(blob, node.topology.uniqueTriangles);
    append(blob, node.topology.edges);
    append(blob, node.topology.boundaryEdges);
    append(blob, node.topology.nonManifoldEdges);
    append(blob, node.topology.duplicateTriangles);
    append(blob, node.topology.degenerateTriangles);
    append(blob, node.topology.flippedTriangles);
    append(blob, node.topology.minTriangleQuality);
    append(blob, node.topology.meanTriangleQuality);
    append(blob, node.attributes.meanNormalErrorRadians);
    append(blob, node.attributes.maxNormalErrorRadians);
    append(blob, node.attributes.meanUvError);
    append(blob, node.attributes.maxUvError);
    append(blob, node.attributes.samples);
    uint8_t const approximated = node.attributes.approximated ? 1 : 0;
    append(blob, approximated);
    append(blob, uint8_t(0));
    append(blob, uint8_t(0));
    append(blob, uint8_t(0));
    for (uint32_t child: node.children) {
        append(blob, child);
    }
    for (uint32_t index: node.indices) {
        append(blob, index);
    }
}

bool readNodeAt(std::vector<uint8_t> const& blob, uint64_t offset, LodGraphNode* node) {
    if (offset > blob.size() || blob.size() - offset < NODE_RECORD_SIZE) {
        return false;
    }
    size_t cursor = size_t(offset);
    uint32_t childCount = 0;
    uint32_t indexCount = 0;
    uint8_t simplified = 0;
    read(blob, &cursor, &node->level);
    read(blob, &cursor, &node->parent);
    read(blob, &cursor, &node->materialId);
    read(blob, &cursor, &node->submeshId);
    read(blob, &cursor, &childCount);
    read(blob, &cursor, &indexCount);
    read(blob, &cursor, &node->baseTriangles);
    read(blob, &cursor, &node->selfError);
    read(blob, &cursor, &node->accumulatedError);
    read(blob, &cursor, &node->bounds.center.x);
    read(blob, &cursor, &node->bounds.center.y);
    read(blob, &cursor, &node->bounds.center.z);
    read(blob, &cursor, &node->bounds.radius);
    read(blob, &cursor, &node->cone.apex.x);
    read(blob, &cursor, &node->cone.apex.y);
    read(blob, &cursor, &node->cone.apex.z);
    read(blob, &cursor, &node->cone.axis.x);
    read(blob, &cursor, &node->cone.axis.y);
    read(blob, &cursor, &node->cone.axis.z);
    read(blob, &cursor, &node->cone.cutoff);
    read(blob, &cursor, &simplified);
    uint8_t padding = 0;
    read(blob, &cursor, &padding);
    read(blob, &cursor, &padding);
    read(blob, &cursor, &padding);
    node->simplified = simplified != 0;
    read(blob, &cursor, &node->topology.triangles);
    read(blob, &cursor, &node->topology.uniqueTriangles);
    read(blob, &cursor, &node->topology.edges);
    read(blob, &cursor, &node->topology.boundaryEdges);
    read(blob, &cursor, &node->topology.nonManifoldEdges);
    read(blob, &cursor, &node->topology.duplicateTriangles);
    read(blob, &cursor, &node->topology.degenerateTriangles);
    read(blob, &cursor, &node->topology.flippedTriangles);
    read(blob, &cursor, &node->topology.minTriangleQuality);
    read(blob, &cursor, &node->topology.meanTriangleQuality);
    read(blob, &cursor, &node->attributes.meanNormalErrorRadians);
    read(blob, &cursor, &node->attributes.maxNormalErrorRadians);
    read(blob, &cursor, &node->attributes.meanUvError);
    read(blob, &cursor, &node->attributes.maxUvError);
    read(blob, &cursor, &node->attributes.samples);
    uint8_t approximated = 0;
    read(blob, &cursor, &approximated);
    read(blob, &cursor, &padding);
    read(blob, &cursor, &padding);
    read(blob, &cursor, &padding);
    node->attributes.approximated = approximated != 0;

    if (childCount > (blob.size() - cursor) / sizeof(uint32_t)) {
        return false;
    }
    node->children.resize(childCount);
    for (uint32_t& child: node->children) {
        if (!read(blob, &cursor, &child)) {
            return false;
        }
    }
    if (indexCount > (blob.size() - cursor) / sizeof(uint32_t)) {
        return false;
    }
    node->indices.resize(indexCount);
    for (uint32_t& index: node->indices) {
        if (!read(blob, &cursor, &index)) {
            return false;
        }
    }
    return true;
}

} // anonymous namespace

std::vector<uint8_t> serializeLodGraph(LodGraph const& graph) {
    std::vector<uint8_t> blob;
    blob.reserve(graph.nodes.size() * 128 + 1024);
    append(&blob, MAGIC);
    append(&blob, VERSION);
    append(&blob, uint32_t(graph.nodes.size()));
    append(&blob, uint32_t(graph.roots.size()));
    append(&blob, uint32_t(graph.leaves.size()));
    append(&blob, graph.levelCount);
    append(&blob, graph.baseTriangles);
    for (uint32_t root: graph.roots) {
        append(&blob, root);
    }
    for (uint32_t leaf: graph.leaves) {
        append(&blob, leaf);
    }

    size_t const offsetsPosition = blob.size();
    blob.resize(blob.size() + (graph.nodes.size() + 1) * sizeof(uint64_t));
    std::vector<uint64_t> offsets(graph.nodes.size() + 1, 0);
    for (size_t i = 0; i < graph.nodes.size(); ++i) {
        offsets[i] = blob.size();
        writeNode(&blob, graph.nodes[i]);
    }
    offsets[graph.nodes.size()] = blob.size();
    for (size_t i = 0; i < offsets.size(); ++i) {
        patchU64(&blob, offsetsPosition + i * sizeof(uint64_t), offsets[i]);
    }
    return blob;
}

bool writeLodGraphFile(LodGraph const& graph, char const* path) {
    if (path == nullptr) {
        return false;
    }
    std::vector<uint8_t> const blob = serializeLodGraph(graph);
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    if (!file) {
        return false;
    }
    file.write(reinterpret_cast<char const*>(blob.data()), std::streamsize(blob.size()));
    return bool(file);
}

bool deserializeLodGraph(std::vector<uint8_t> const& blob, LodGraph* graph) {
    StreamingLodGraph streaming(blob);
    if (!streaming.valid() || graph == nullptr) {
        return false;
    }
    graph->nodes.resize(streaming.nodeCount());
    for (uint32_t i = 0; i < streaming.nodeCount(); ++i) {
        if (!streaming.readNode(i, &graph->nodes[i])) {
            return false;
        }
    }
    graph->roots = streaming.roots();
    graph->leaves = streaming.leaves();
    graph->levelCount = streaming.levelCount();
    graph->baseTriangles = streaming.baseTriangles();
    return true;
}

std::vector<LodStreamingPage> planLodStreamingPages(std::vector<uint8_t> const& blob,
        size_t maxPageBytes) {
    StreamingLodGraph const streaming(blob);
    return streaming.valid() ? streaming.planPages(maxPageBytes) : std::vector<LodStreamingPage>{};
}

StreamingLodGraph::StreamingLodGraph(std::vector<uint8_t> blob)
        : mBlob(std::move(blob)) {
    mBlobSize = mBlob.size();
    size_t cursor = 0;
    uint32_t magic = 0;
    uint32_t version = 0;
    uint32_t rootCount = 0;
    uint32_t leafCount = 0;
    if (!read(mBlob, &cursor, &magic) || !read(mBlob, &cursor, &version) || magic != MAGIC ||
            version != VERSION || !read(mBlob, &cursor, &mNodeCount) ||
            !read(mBlob, &cursor, &rootCount) || !read(mBlob, &cursor, &leafCount) ||
            !read(mBlob, &cursor, &mLevelCount) || !read(mBlob, &cursor, &mBaseTriangles)) {
        return;
    }
    mRoots.resize(rootCount);
    for (uint32_t& root: mRoots) {
        if (!read(mBlob, &cursor, &root)) {
            return;
        }
    }
    mLeaves.resize(leafCount);
    for (uint32_t& leaf: mLeaves) {
        if (!read(mBlob, &cursor, &leaf)) {
            return;
        }
    }
    mOffsets.resize(size_t(mNodeCount) + 1);
    for (uint64_t& offset: mOffsets) {
        if (!read(mBlob, &cursor, &offset)) {
            return;
        }
    }
    for (size_t i = 1; i < mOffsets.size(); ++i) {
        if (mOffsets[i] < mOffsets[i - 1] || mOffsets[i] > mBlob.size()) {
            return;
        }
    }
    if (mOffsets.empty() || mOffsets.back() != mBlob.size()) {
        return;
    }
    mValid = true;
}

StreamingLodGraph::StreamingLodGraph(std::string const& path) {
    mFile.open(path, std::ios::binary);
    if (!mFile) {
        return;
    }
    mFile.seekg(0, std::ios::end);
    std::streamoff const fileSize = mFile.tellg();
    if (fileSize < 0) {
        return;
    }
    mBlobSize = uint64_t(fileSize);
    mFile.seekg(0, std::ios::beg);

    uint32_t magic = 0;
    uint32_t version = 0;
    uint32_t rootCount = 0;
    uint32_t leafCount = 0;
    if (!readStream(mFile, &magic) || !readStream(mFile, &version) || magic != MAGIC ||
            version != VERSION || !readStream(mFile, &mNodeCount) ||
            !readStream(mFile, &rootCount) || !readStream(mFile, &leafCount) ||
            !readStream(mFile, &mLevelCount) || !readStream(mFile, &mBaseTriangles)) {
        return;
    }
    // Reject counts that cannot possibly fit in the file before allocating for them.
    if (uint64_t(rootCount) * sizeof(uint32_t) > mBlobSize ||
            uint64_t(leafCount) * sizeof(uint32_t) > mBlobSize ||
            uint64_t(mNodeCount + 1) * sizeof(uint64_t) > mBlobSize) {
        return;
    }
    mRoots.resize(rootCount);
    for (uint32_t& root: mRoots) {
        if (!readStream(mFile, &root)) {
            return;
        }
    }
    mLeaves.resize(leafCount);
    for (uint32_t& leaf: mLeaves) {
        if (!readStream(mFile, &leaf)) {
            return;
        }
    }
    mOffsets.resize(size_t(mNodeCount) + 1);
    for (uint64_t& offset: mOffsets) {
        if (!readStream(mFile, &offset)) {
            return;
        }
    }
    for (size_t i = 1; i < mOffsets.size(); ++i) {
        if (mOffsets[i] < mOffsets[i - 1] || mOffsets[i] > mBlobSize) {
            return;
        }
    }
    if (mOffsets.empty() || mOffsets.back() != mBlobSize) {
        return;
    }
    mValid = true;
}

uint64_t StreamingLodGraph::nodeOffset(uint32_t nodeId) const {
    return nodeId < mOffsets.size() ? mOffsets[nodeId] : 0;
}

bool StreamingLodGraph::readRange(uint64_t offset, size_t size, std::vector<uint8_t>* out) const {
    if (out == nullptr || offset > mBlobSize || size > mBlobSize - offset) {
        return false;
    }
    out->resize(size);
    if (size == 0) {
        return true;
    }
    if (mFile.is_open()) {
        std::lock_guard<std::mutex> lock(mFileMutex);
        mFile.clear();
        mFile.seekg(std::streamoff(offset), std::ios::beg);
        mFile.read(reinterpret_cast<char*>(out->data()), std::streamsize(size));
        return bool(mFile);
    }
    std::memcpy(out->data(), mBlob.data() + size_t(offset), size);
    return true;
}

bool StreamingLodGraph::readNode(uint32_t nodeId, LodGraphNode* node) const {
    if (!mValid || node == nullptr || nodeId >= mNodeCount) {
        return false;
    }
    if (mFile.is_open()) {
        uint64_t const offset = nodeOffset(nodeId);
        uint64_t const end = nodeOffset(nodeId + 1);
        std::vector<uint8_t> record;
        return readRange(offset, size_t(end - offset), &record) && readNodeAt(record, 0, node);
    }
    return readNodeAt(mBlob, nodeOffset(nodeId), node);
}

bool StreamingLodGraph::readPage(LodStreamingPage const& page,
        std::vector<LodGraphNode>* nodes) const {
    if (!mValid || nodes == nullptr || page.firstNode > mNodeCount ||
            page.nodeCount > mNodeCount - page.firstNode) {
        return false;
    }
    nodes->resize(page.nodeCount);
    if (mFile.is_open()) {
        std::vector<uint8_t> pageData;
        if (!readRange(page.byteOffset, size_t(page.byteCount), &pageData)) {
            return false;
        }
        for (uint32_t i = 0; i < page.nodeCount; ++i) {
            uint32_t const nodeId = page.firstNode + i;
            uint64_t const relative = nodeOffset(nodeId) - page.byteOffset;
            if (relative > pageData.size() || !readNodeAt(pageData, relative, &(*nodes)[i])) {
                return false;
            }
        }
        return true;
    }
    for (uint32_t i = 0; i < page.nodeCount; ++i) {
        if (!readNode(page.firstNode + i, &(*nodes)[i])) {
            return false;
        }
    }
    return true;
}

std::vector<LodStreamingPage> StreamingLodGraph::planPages(size_t maxPageBytes) const {
    std::vector<LodStreamingPage> pages;
    if (!mValid || mNodeCount == 0) {
        return pages;
    }
    maxPageBytes = std::max<size_t>(maxPageBytes, 1);
    uint32_t first = 0;
    while (first < mNodeCount) {
        uint64_t const start = mOffsets[first];
        uint32_t last = first;
        while (last + 2 <= mNodeCount && mOffsets[last + 2] - start <= maxPageBytes) {
            last += 1;
        }
        LodStreamingPage page;
        page.firstNode = first;
        page.nodeCount = last - first + 1;
        page.byteOffset = start;
        page.byteCount = mOffsets[last + 1] - start;
        pages.push_back(page);
        first = last + 1;
    }
    return pages;
}

LodStreamingCache::LodStreamingCache(StreamingLodGraph const* graph, size_t byteBudget,
        size_t maxPageBytes)
        : mGraph(graph),
          mByteBudget(byteBudget),
          mMaxPageBytes(std::max<size_t>(maxPageBytes, 1)) {
    if (mGraph != nullptr && mGraph->valid()) {
        mPages = mGraph->planPages(mMaxPageBytes);
    }
}

bool LodStreamingCache::prepare(LodGraphSelection const& selection) {
    if (mGraph == nullptr || !mGraph->valid()) {
        return false;
    }

    std::set<uint32_t> required;
    for (uint32_t nodeId: selection.nodes) {
        auto const page = std::upper_bound(mPages.begin(), mPages.end(), nodeId,
                [](uint32_t id, LodStreamingPage const& candidate) {
                    return id < candidate.firstNode;
                });
        if (page == mPages.begin()) {
            return false;
        }
        auto const selected = std::prev(page);
        if (selected->firstNode + selected->nodeCount <= nodeId) {
            return false;
        }
        required.insert(uint32_t(selected - mPages.begin()));
    }

    for (uint32_t pageId: required) {
        auto found = mResident.find(pageId);
        if (found == mResident.end()) {
            PageEntry entry;
            entry.page = mPages[pageId];
            if (!mGraph->readPage(entry.page, &entry.nodes)) {
                return false;
            }
            mStats.residentBytes += size_t(entry.page.byteCount);
            mStats.pageMisses += 1;
            found = mResident.emplace(pageId, std::move(entry)).first;
        } else {
            mStats.pageHits += 1;
        }
        mLru.remove(pageId);
        mLru.push_front(pageId);
        (void) found;
    }

    while (mStats.residentBytes > mByteBudget && !mLru.empty()) {
        uint32_t victim = UINT32_MAX;
        for (auto it = mLru.rbegin(); it != mLru.rend(); ++it) {
            if (required.count(*it) == 0) {
                victim = *it;
                break;
            }
        }
        if (victim == UINT32_MAX) {
            break; // every resident page is needed by this selection
        }
        auto found = mResident.find(victim);
        if (found != mResident.end()) {
            mStats.residentBytes -= size_t(found->second.page.byteCount);
            mResident.erase(found);
            mStats.evictions += 1;
        }
        mLru.remove(victim);
    }

    mStats.residentPages = mResident.size();
    return true;
}

LodGraphNode const* LodStreamingCache::find(uint32_t nodeId) const {
    for (auto const& [pageId, entry]: mResident) {
        (void) pageId;
        if (nodeId >= entry.page.firstNode &&
                nodeId < entry.page.firstNode + entry.page.nodeCount) {
            return &entry.nodes[nodeId - entry.page.firstNode];
        }
    }
    return nullptr;
}

AsyncLodStreamingCache::AsyncLodStreamingCache(StreamingLodGraph const* graph, PageFetcher fetcher,
        size_t byteBudget, size_t maxPageBytes, size_t maxConcurrent)
        : mGraph(graph),
          mFetcher(std::move(fetcher)),
          mByteBudget(byteBudget),
          mMaxPageBytes(std::max<size_t>(maxPageBytes, 1)),
          mMaxConcurrent(std::max<size_t>(maxConcurrent, 1)) {
    if (mGraph != nullptr && mGraph->valid()) {
        mPages = mGraph->planPages(mMaxPageBytes);
    }
}

bool AsyncLodStreamingCache::request(LodGraphSelection const& selection) {
    if (mGraph == nullptr || !mGraph->valid() || !mFetcher) {
        return false;
    }

    mRequired.clear();
    for (uint32_t nodeId: selection.nodes) {
        auto const page = std::upper_bound(mPages.begin(), mPages.end(), nodeId,
                [](uint32_t id, LodStreamingPage const& candidate) {
                    return id < candidate.firstNode;
                });
        if (page == mPages.begin()) {
            return false;
        }
        auto const selected = std::prev(page);
        if (selected->firstNode + selected->nodeCount <= nodeId) {
            return false;
        }
        uint32_t const pageId = uint32_t(selected - mPages.begin());
        mRequired.insert(pageId);
        if (mResident.count(pageId) != 0) {
            mStats.pageHits += 1;
            mLru.remove(pageId);
            mLru.push_front(pageId);
        } else if (mRequested.insert(pageId).second) {
            mQueue.push_back(pageId);
        }
    }
    pump();
    return true;
}

void AsyncLodStreamingCache::pump() {
    while (mPending.size() < mMaxConcurrent && !mQueue.empty()) {
        uint32_t const pageId = mQueue.front();
        mQueue.pop_front();
        LodStreamingPage const page = mPages[pageId];
        mPending.push_back(std::async(std::launch::async, [this, pageId, page]() -> PageResult {
            PageResult result;
            result.pageId = pageId;
            result.page = page;
            try {
                result.ok = mFetcher(page, &result.nodes);
            } catch (...) {
                result.ok = false;
            }
            return result;
        }));
    }
}

bool AsyncLodStreamingCache::poll() {
    bool arrived = false;
    while (true) {
        bool consumed = false;
        for (auto it = mPending.begin(); it != mPending.end(); ++it) {
            if (it->wait_for(std::chrono::milliseconds(0)) != std::future_status::ready) {
                continue;
            }
            PageResult result = it->get();
            mPending.erase(it);
            mRequested.erase(result.pageId);
            if (result.ok) {
                mStats.pageMisses += 1;
                mStats.residentBytes += size_t(result.page.byteCount);
                mResident[result.pageId] = std::move(result.nodes);
                mLru.remove(result.pageId);
                mLru.push_front(result.pageId);
            } else {
                // A failed page is not marked resident, so a later request retries it.
            }
            arrived = true;
            consumed = true;
            break;
        }
        if (!consumed) {
            break;
        }
    }

    pump();
    evict();
    mStats.residentPages = mResident.size();
    return arrived;
}

void AsyncLodStreamingCache::evict() {
    while (mStats.residentBytes > mByteBudget && !mLru.empty()) {
        uint32_t victim = UINT32_MAX;
        for (auto it = mLru.rbegin(); it != mLru.rend(); ++it) {
            if (mRequired.count(*it) == 0) {
                victim = *it;
                break;
            }
        }
        if (victim == UINT32_MAX) {
            break; // every resident page is needed by this selection
        }
        auto const found = mResident.find(victim);
        if (found != mResident.end()) {
            mStats.residentBytes -= size_t(mPages[victim].byteCount);
            mResident.erase(found);
            mStats.evictions += 1;
        }
        mLru.remove(victim);
    }
}

LodGraphNode const* AsyncLodStreamingCache::find(uint32_t nodeId) const {
    for (auto const& [pageId, nodes]: mResident) {
        LodStreamingPage const& page = mPages[pageId];
        if (nodeId >= page.firstNode && nodeId < page.firstNode + page.nodeCount) {
            return &nodes[nodeId - page.firstNode];
        }
    }
    return nullptr;
}

} // namespace manymesh
} // namespace filament

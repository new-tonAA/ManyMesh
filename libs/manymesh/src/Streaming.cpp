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

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <winhttp.h>
#endif

namespace filament {
namespace manymesh {

namespace {

constexpr uint32_t MAGIC = 0x474C4D4Du; // "MMLG" in little-endian byte order
// Version 3 appends the source vertex count. Version 2 remains readable so previously written
// graph files still stream; the loader derives the vertex count from the records in that case.
// The layout still has one fixed-size prefix followed by variable child/index arrays, so a
// runtime can keep reading individual nodes without deserializing the whole graph.
constexpr uint32_t VERSION = 3u;
constexpr uint32_t MIN_VERSION = 2u;
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

bool readNodeAt(std::vector<uint8_t> const& blob, uint64_t offset, LodGraphNode* node,
        size_t* endOffset = nullptr) {
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

    if (uint64_t(childCount) + uint64_t(indexCount) > (blob.size() - cursor) / sizeof(uint32_t)) {
        return false;
    }
    node->children.resize(childCount);
    for (uint32_t& child: node->children) {
        if (!read(blob, &cursor, &child)) {
            return false;
        }
    }
    node->indices.resize(indexCount);
    for (uint32_t& index: node->indices) {
        if (!read(blob, &cursor, &index)) {
            return false;
        }
    }
    if (endOffset != nullptr) {
        *endOffset = cursor;
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
    append(&blob, graph.vertexCount);
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
    graph->vertexCount = streaming.vertexCount();
    if (graph->vertexCount == 0) {
        // Version 2 did not store the count. Recover it from the node index lists.
        for (LodGraphNode const& node: graph->nodes) {
            for (uint32_t index: node.indices) {
                graph->vertexCount = std::max(graph->vertexCount, index + 1);
            }
        }
    }
    return true;
}

bool decodeLodStreamingPage(std::vector<uint8_t> const& pageBytes, LodStreamingPage const& page,
        std::vector<LodGraphNode>* nodes) {
    if (nodes == nullptr) {
        return false;
    }
    nodes->resize(page.nodeCount);
    size_t cursor = 0;
    for (uint32_t i = 0; i < page.nodeCount; ++i) {
        if (!readNodeAt(pageBytes, cursor, &(*nodes)[i], &cursor)) {
            return false;
        }
    }
    return true;
}

std::vector<LodStreamingPage> planLodStreamingPages(std::vector<uint8_t> const& blob,
        size_t maxPageBytes) {
    StreamingLodGraph const streaming(blob);
    return streaming.valid() ? streaming.planPages(maxPageBytes) : std::vector<LodStreamingPage>{};
}

namespace {

bool validateNodePages(std::vector<LodStreamingPage> const& pages,
        std::vector<uint32_t> const& nodes) {
    for (uint32_t nodeId: nodes) {
        auto const page = std::upper_bound(pages.begin(), pages.end(), nodeId,
                [](uint32_t id, LodStreamingPage const& candidate) {
                    return id < candidate.firstNode;
                });
        if (page == pages.begin()) {
            return false;
        }
        auto const selected = std::prev(page);
        if (selected->firstNode + selected->nodeCount <= nodeId) {
            return false;
        }
    }
    return true;
}

void collectRequiredPages(std::vector<LodStreamingPage> const& pages,
        std::vector<uint32_t> const& nodes, std::vector<uint32_t>* required) {
    required->clear();
    required->reserve(nodes.size());
    for (uint32_t nodeId: nodes) {
        auto const page = std::upper_bound(pages.begin(), pages.end(), nodeId,
                [](uint32_t id, LodStreamingPage const& candidate) {
                    return id < candidate.firstNode;
                });
        auto const selected = std::prev(page);
        required->push_back(uint32_t(selected - pages.begin()));
    }
    std::sort(required->begin(), required->end());
    required->erase(std::unique(required->begin(), required->end()), required->end());
}

} // namespace

StreamingLodGraph::StreamingLodGraph(std::vector<uint8_t> blob)
        : mBlob(std::move(blob)) {
    mBlobSize = mBlob.size();
    size_t cursor = 0;
    uint32_t magic = 0;
    uint32_t version = 0;
    uint32_t rootCount = 0;
    uint32_t leafCount = 0;
    if (!read(mBlob, &cursor, &magic) || !read(mBlob, &cursor, &version) || magic != MAGIC ||
            version < MIN_VERSION || version > VERSION || !read(mBlob, &cursor, &mNodeCount) ||
            !read(mBlob, &cursor, &rootCount) || !read(mBlob, &cursor, &leafCount) ||
            !read(mBlob, &cursor, &mLevelCount) || !read(mBlob, &cursor, &mBaseTriangles) ||
            (version >= 3u && !read(mBlob, &cursor, &mVertexCount))) {
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
            version < MIN_VERSION || version > VERSION || !readStream(mFile, &mNodeCount) ||
            !readStream(mFile, &rootCount) || !readStream(mFile, &leafCount) ||
            !readStream(mFile, &mLevelCount) || !readStream(mFile, &mBaseTriangles) ||
            (version >= 3u && !readStream(mFile, &mVertexCount))) {
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

bool StreamingLodGraph::readBytes(uint64_t offset, size_t size, std::vector<uint8_t>* out) const {
    return mValid && readRange(offset, size, out);
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

    std::vector<uint32_t> required;
    if (!validateNodePages(mPages, selection.nodes)) {
        return false;
    }
    collectRequiredPages(mPages, selection.nodes, &required);

    for (uint32_t pageId: required) {
        auto found = mResident.find(pageId);
        if (found == mResident.end()) {
            PageEntry entry;
            entry.page = mPages[pageId];
            if (!mGraph->readPage(entry.page, &entry.nodes)) {
                return false;
            }
            mStats.residentBytes += size_t(entry.page.byteCount);
            mStats.bytesFetched += entry.page.byteCount;
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
            if (!std::binary_search(required.begin(), required.end(), *it)) {
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

bool LodStreamingCache::prepare(LodGraphCut const& cut) {
    LodGraphSelection selection;
    selection.nodes = cut.nodes;
    return prepare(selection);
}

LodGraphNode const* LodStreamingCache::find(uint32_t nodeId) const {
    auto const page = std::upper_bound(mPages.begin(), mPages.end(), nodeId,
            [](uint32_t id, LodStreamingPage const& candidate) {
                return id < candidate.firstNode;
            });
    if (page == mPages.begin()) {
        return nullptr;
    }
    auto const selected = std::prev(page);
    if (nodeId >= selected->firstNode + selected->nodeCount) {
        return nullptr;
    }
    auto const resident = mResident.find(uint32_t(selected - mPages.begin()));
    if (resident == mResident.end()) {
        return nullptr;
    }
    return &resident->second.nodes[nodeId - selected->firstNode];
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

AsyncLodStreamingCache::AsyncLodStreamingCache(StreamingLodGraph const* graph,
        ByteRangeFetcher fetcher, size_t byteBudget, size_t maxPageBytes, size_t maxConcurrent)
        : AsyncLodStreamingCache(graph,
                  PageFetcher([fetcher = std::move(fetcher)](LodStreamingPage const& page,
                                      std::vector<LodGraphNode>* nodes) {
                      if (!fetcher) {
                          return false;
                      }
                      std::vector<uint8_t> bytes;
                      if (!fetcher(page.byteOffset, size_t(page.byteCount), &bytes)) {
                          return false;
                      }
                      return decodeLodStreamingPage(bytes, page, nodes);
                  }),
                  byteBudget, maxPageBytes, maxConcurrent) {}

bool AsyncLodStreamingCache::request(LodGraphSelection const& selection) {
    return requestNodes(selection.nodes);
}

bool AsyncLodStreamingCache::request(LodGraphCut const& cut) { return requestNodes(cut.nodes); }

bool AsyncLodStreamingCache::requestNodes(std::vector<uint32_t> const& nodes) {
    if (mGraph == nullptr || !mGraph->valid() || !mFetcher) {
        return false;
    }

    // Validate the whole request first so a bad node cannot leave a half-updated queue.
    if (!validateNodePages(mPages, nodes)) {
        return false;
    }
    collectRequiredPages(mPages, nodes, &mRequired);

    // A rapidly changing camera can leave pages from an older cut queued. Drop the ones that
    // have not started yet; already-running fetches are left alone and their results are still
    // cached for a later request.
    mQueue.erase(std::remove_if(mQueue.begin(), mQueue.end(),
                         [this](uint32_t pageId) {
                             if (std::binary_search(mRequired.begin(), mRequired.end(), pageId)) {
                                 return false;
                             }
                             mRequested.erase(pageId);
                             return true;
                         }),
            mQueue.end());

    for (uint32_t pageId: mRequired) {
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
        try {
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
        } catch (...) {
            // Thread creation failed. Leave the page retryable instead of losing it forever.
            mRequested.erase(pageId);
            break;
        }
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
                mStats.bytesFetched += result.page.byteCount;
                auto const inserted = mResident.emplace(result.pageId, std::move(result.nodes));
                if (!inserted.second) {
                    mStats.residentBytes -= size_t(result.page.byteCount);
                    inserted.first->second = std::move(result.nodes);
                }
                mStats.residentBytes += size_t(result.page.byteCount);
                mLru.remove(result.pageId);
                mLru.push_front(result.pageId);
            } else {
                // A failed page is not marked resident, so a later request retries it.
                mStats.failedFetches += 1;
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
            if (!std::binary_search(mRequired.begin(), mRequired.end(), *it)) {
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
    auto const page = std::upper_bound(mPages.begin(), mPages.end(), nodeId,
            [](uint32_t id, LodStreamingPage const& candidate) {
                return id < candidate.firstNode;
            });
    if (page == mPages.begin()) {
        return nullptr;
    }
    auto const selected = std::prev(page);
    if (nodeId >= selected->firstNode + selected->nodeCount) {
        return nullptr;
    }
    auto const resident = mResident.find(uint32_t(selected - mPages.begin()));
    if (resident == mResident.end()) {
        return nullptr;
    }
    return &resident->second[nodeId - selected->firstNode];
}

struct HttpByteRangeFetcher::Impl {
    std::string url;
    std::string error;
    unsigned timeoutMs = 5000;
    bool valid = false;
    HttpByteRangeFetcher::RangeFetcher platformFetcher;

#if defined(_WIN32)
    bool https = false;
    INTERNET_PORT port = 80;
    std::wstring host;
    std::wstring path;
#endif
};

namespace {

#if defined(_WIN32)

std::wstring widen(std::string const& value) {
    if (value.empty()) {
        return {};
    }
    int const length = MultiByteToWideChar(CP_UTF8, 0, value.data(), int(value.size()), nullptr, 0);
    if (length <= 0) {
        return {};
    }
    std::wstring result(size_t(length), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), int(value.size()), result.data(), length);
    return result;
}

bool parsePort(std::string const& text, INTERNET_PORT* port) {
    if (text.empty()) {
        return false;
    }
    uint32_t value = 0;
    for (char c: text) {
        if (c < '0' || c > '9') {
            return false;
        }
        value = value * 10u + uint32_t(c - '0');
        if (value > 65535u) {
            return false;
        }
    }
    if (value == 0) {
        return false;
    }
    *port = INTERNET_PORT(value);
    return true;
}

bool isLoopbackHost(std::wstring const& host) {
    return host == L"localhost" || host == L"127.0.0.1" || host == L"::1";
}

class InternetHandle {
public:
    explicit InternetHandle(HINTERNET handle = nullptr)
            : mHandle(handle) {}
    ~InternetHandle() {
        if (mHandle != nullptr) {
            WinHttpCloseHandle(mHandle);
        }
    }
    InternetHandle(InternetHandle const&) = delete;
    InternetHandle& operator=(InternetHandle const&) = delete;
    operator HINTERNET() const { return mHandle; }
    explicit operator bool() const { return mHandle != nullptr; }
    HINTERNET get() const { return mHandle; }

private:
    HINTERNET mHandle = nullptr;
};

struct ParsedHttpUrl {
    bool https = false;
    INTERNET_PORT port = 80;
    std::wstring host;
    std::wstring path;
};

bool parseHttpUrl(std::string const& url, ParsedHttpUrl* parsed, std::string* error) {
    std::string rest;
    if (url.rfind("https://", 0) == 0) {
        parsed->https = true;
        parsed->port = 443;
        rest = url.substr(8);
    } else if (url.rfind("http://", 0) == 0) {
        parsed->https = false;
        parsed->port = 80;
        rest = url.substr(7);
    } else {
        *error = "URL must start with http:// or https://";
        return false;
    }

    size_t const tailIndex = rest.find_first_of("/?#");
    std::string authority = rest.substr(0, tailIndex);
    std::string tail = tailIndex == std::string::npos ? std::string() : rest.substr(tailIndex);
    if (tail.empty() || tail[0] == '?' || tail[0] == '#') {
        tail = "/" + tail;
    }
    parsed->path = widen(tail);
    if (parsed->path.empty()) {
        parsed->path = L"/";
    }

    if (authority.empty()) {
        *error = "URL has no host";
        return false;
    }

    std::string host = authority;
    if (authority.front() == '[') {
        size_t const close = authority.find(']');
        if (close == std::string::npos) {
            *error = "URL has an unterminated IPv6 host";
            return false;
        }
        host = authority.substr(1, close - 1);
        if (close + 1 < authority.size()) {
            if (authority[close + 1] != ':' ||
                    !parsePort(authority.substr(close + 2), &parsed->port)) {
                *error = "URL has an invalid port";
                return false;
            }
        }
    } else {
        size_t const colon = authority.rfind(':');
        if (colon != std::string::npos) {
            if (authority.find(':') != colon) {
                *error = "IPv6 hosts must be wrapped in brackets";
                return false;
            }
            host = authority.substr(0, colon);
            if (!parsePort(authority.substr(colon + 1), &parsed->port)) {
                *error = "URL has an invalid port";
                return false;
            }
        }
    }
    parsed->host = widen(host);
    if (parsed->host.empty()) {
        *error = "URL has no host";
        return false;
    }
    return true;
}

#endif

} // namespace

HttpByteRangeFetcher::HttpByteRangeFetcher(std::string url, unsigned timeoutMs)
        : mImpl(new Impl()) {
    mImpl->url = std::move(url);
    mImpl->timeoutMs = std::max(timeoutMs, 1u);
#if defined(_WIN32)
    ParsedHttpUrl parsed;
    mImpl->valid = parseHttpUrl(mImpl->url, &parsed, &mImpl->error);
    if (mImpl->valid) {
        mImpl->https = parsed.https;
        mImpl->port = parsed.port;
        mImpl->host = std::move(parsed.host);
        mImpl->path = std::move(parsed.path);
    }
#else
    mImpl->error = "HTTP transport is not implemented for this platform";
#endif
}

HttpByteRangeFetcher::HttpByteRangeFetcher(std::string url, RangeFetcher fetcher,
        unsigned timeoutMs)
        : mImpl(new Impl()) {
    mImpl->url = std::move(url);
    mImpl->timeoutMs = std::max(timeoutMs, 1u);
    mImpl->platformFetcher = std::move(fetcher);
    mImpl->valid = bool(mImpl->platformFetcher);
    if (!mImpl->valid) {
        mImpl->error = "injected HTTP transport is empty";
    }
}

HttpByteRangeFetcher::~HttpByteRangeFetcher() = default;

bool HttpByteRangeFetcher::valid() const noexcept { return mImpl && mImpl->valid; }

std::string const& HttpByteRangeFetcher::url() const noexcept {
    static std::string const empty;
    return mImpl ? mImpl->url : empty;
}

std::string const& HttpByteRangeFetcher::lastError() const noexcept {
    static std::string const empty;
    return mImpl ? mImpl->error : empty;
}

AsyncLodStreamingCache::ByteRangeFetcher HttpByteRangeFetcher::asFetcher() {
    return [this](uint64_t offset, size_t size, std::vector<uint8_t>* bytes) {
        return fetch(offset, size, bytes);
    };
}

bool HttpByteRangeFetcher::fetch(uint64_t offset, size_t size, std::vector<uint8_t>* bytes) {
    if (bytes == nullptr) {
        return false;
    }
    bytes->clear();
    if (!mImpl) {
        return false;
    }
    if (!mImpl->valid) {
        return false;
    }
    if (size == 0) {
        return true;
    }

    if (mImpl->platformFetcher) {
        mImpl->error.clear();
        if (!mImpl->platformFetcher(offset, size, bytes, &mImpl->error)) {
            if (mImpl->error.empty()) {
                mImpl->error = "injected HTTP transport failed";
            }
            bytes->clear();
            return false;
        }
        if (bytes->size() != size) {
            mImpl->error = "injected HTTP transport returned " + std::to_string(bytes->size()) +
                           " bytes, expected " + std::to_string(size);
            bytes->clear();
            return false;
        }
        return true;
    }

#if defined(_WIN32)
    mImpl->error.clear();
    DWORD const accessType = isLoopbackHost(mImpl->host) ? WINHTTP_ACCESS_TYPE_NO_PROXY
                                                         : WINHTTP_ACCESS_TYPE_DEFAULT_PROXY;
    InternetHandle session(WinHttpOpen(L"ManyMesh/1.0", accessType, WINHTTP_NO_PROXY_NAME,
            WINHTTP_NO_PROXY_BYPASS, 0));
    if (!session) {
        mImpl->error = "WinHttpOpen failed";
        return false;
    }
    int const timeout = int(std::min(mImpl->timeoutMs, unsigned(INT_MAX)));
    WinHttpSetTimeouts(session.get(), timeout, timeout, timeout, timeout);

    InternetHandle connection(WinHttpConnect(session.get(), mImpl->host.c_str(), mImpl->port, 0));
    if (!connection) {
        mImpl->error = "WinHttpConnect failed";
        return false;
    }

    DWORD const flags = mImpl->https ? WINHTTP_FLAG_SECURE : 0;
    InternetHandle request(WinHttpOpenRequest(connection.get(), L"GET", mImpl->path.c_str(),
            nullptr, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, flags));
    if (!request) {
        mImpl->error = "WinHttpOpenRequest failed";
        return false;
    }

    DWORD const redirectPolicy = WINHTTP_OPTION_REDIRECT_POLICY_ALWAYS;
    WinHttpSetOption(request.get(), WINHTTP_OPTION_REDIRECT_POLICY,
            const_cast<DWORD*>(&redirectPolicy), sizeof(redirectPolicy));

    unsigned long long const end = offset + (size - 1);
    wchar_t header[128];
    swprintf_s(header, 128, L"Range: bytes=%llu-%llu\r\nAccept-Encoding: identity\r\n", offset,
            end);
    if (!WinHttpSendRequest(request.get(), header, -1L, WINHTTP_NO_REQUEST_DATA, 0, 0, 0)) {
        mImpl->error = "WinHttpSendRequest failed";
        return false;
    }
    if (!WinHttpReceiveResponse(request.get(), nullptr)) {
        mImpl->error = "WinHttpReceiveResponse failed";
        return false;
    }

    DWORD status = 0;
    DWORD statusSize = sizeof(status);
    if (!WinHttpQueryHeaders(request.get(), WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                WINHTTP_HEADER_NAME_BY_INDEX, &status, &statusSize, WINHTTP_NO_HEADER_INDEX)) {
        mImpl->error = "WinHttpQueryHeaders failed";
        return false;
    }
    if (status != 206 && !(status == 200 && offset == 0)) {
        mImpl->error =
                "server did not honor the byte range (status " + std::to_string(status) + ")";
        return false;
    }

    bytes->reserve(size);
    std::vector<uint8_t> chunk(std::min<size_t>(size, 64u * 1024u));
    size_t total = 0;
    while (total < size) {
        DWORD read = 0;
        DWORD const want = DWORD(std::min<size_t>(size - total, chunk.size()));
        if (!WinHttpReadData(request.get(), chunk.data(), want, &read)) {
            mImpl->error = "WinHttpReadData failed";
            bytes->clear();
            return false;
        }
        if (read == 0) {
            break;
        }
        bytes->insert(bytes->end(), chunk.begin(), chunk.begin() + read);
        total += read;
    }
    if (total != size) {
        mImpl->error =
                "short read: expected " + std::to_string(size) + ", got " + std::to_string(total);
        bytes->clear();
        return false;
    }
    return true;
#else
    (void) offset;
    (void) size;
    return false;
#endif
}

} // namespace manymesh
} // namespace filament

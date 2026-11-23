import pathlib

path = pathlib.Path(r'E:\ManyMesh\libs\manymesh\src\LodGraph.cpp')
lines = path.read_text(encoding='utf-8').split('\n')
start = 1007 - 1   # '        std::vector<uint32_t> next;'
end = 1085         # exclusive: keep line 1086 ('if (stats != nullptr) {')
assert lines[start].strip() == 'std::vector<uint32_t> next;', repr(lines[start])
assert lines[1084].strip() == '}', repr(lines[1084])
assert 'groupBuildSeconds' in lines[1086], repr(lines[1086])

stats_block = '''                stats->groupCandidates += 1;
                stats->seamLockedVertices += result.seamLockedVertices;
                stats->groupSimplifyCalls += 1;
                stats->groupSimplifyAttempts += result.attempts;
                stats->groupSimplify.attributeQemSeconds += result.profile.attributeQemSeconds;
                stats->groupSimplify.cornerSeconds += result.profile.cornerSeconds;
                stats->groupSimplify.cornerSetupSeconds += result.profile.cornerSetupSeconds;
                stats->groupSimplify.cornerEvaluateSeconds += result.profile.cornerEvaluateSeconds;
                stats->groupSimplify.cornerEvaluateTopologySeconds +=
                        result.profile.cornerEvaluateTopologySeconds;
                stats->groupSimplify.cornerTopologyNeighborSeconds +=
                        result.profile.cornerTopologyNeighborSeconds;
                stats->groupSimplify.cornerTopologyTriangleSeconds +=
                        result.profile.cornerTopologyTriangleSeconds;
                stats->groupSimplify.cornerTopologyLocalTriangleSeconds +=
                        result.profile.cornerTopologyLocalTriangleSeconds;
                stats->groupSimplify.cornerTopologyLocalEdgeSeconds +=
                        result.profile.cornerTopologyLocalEdgeSeconds;
                stats->groupSimplify.cornerEvaluateTargetSeconds +=
                        result.profile.cornerEvaluateTargetSeconds;
                stats->groupSimplify.cornerApplySeconds += result.profile.cornerApplySeconds;
                stats->groupSimplify.cornerEvaluations += result.profile.cornerEvaluations;
                stats->groupSimplify.cornerPlacementTests += result.profile.cornerPlacementTests;
                stats->groupSimplify.cornerApplied += result.profile.cornerApplied;
                stats->groupSimplify.meshoptSeconds += result.profile.meshoptSeconds;
                stats->groupSimplify.candidateGateSeconds += result.profile.candidateGateSeconds;
                stats->groupSimplify.candidateCleanupSeconds +=
                        result.profile.candidateCleanupSeconds;
                stats->groupSimplify.candidateSliverSeconds +=
                        result.profile.candidateSliverSeconds;
                stats->groupSimplify.candidateErrorSeconds += result.profile.candidateErrorSeconds;
                stats->groupSimplify.candidateTopologySeconds +=
                        result.profile.candidateTopologySeconds;
                stats->groupSimplify.weldedTopologySeconds += result.profile.weldedTopologySeconds;
                stats->groupSimplify.boundaryCheckSeconds += result.profile.boundaryCheckSeconds;
                stats->groupSimplify.lockedMaskSeconds += result.profile.lockedMaskSeconds;
                stats->groupSimplify.extendedMeshSeconds += result.profile.extendedMeshSeconds;
                stats->groupSimplify.calls += result.profile.calls;
                stats->groupSimplify.attempts += result.profile.attempts;
                stats->groupSimplify.attributeCandidates += result.profile.attributeCandidates;
                stats->groupSimplify.cornerCandidates += result.profile.cornerCandidates;
                stats->groupSimplify.meshoptCandidates += result.profile.meshoptCandidates;
                stats->groupSimplify.accepted += result.profile.accepted;
                stats->groupSimplify.extendedMeshCopies += result.profile.extendedMeshCopies;
                stats->groupSimplify.rejectedNotSimplified += result.profile.rejectedNotSimplified;
                stats->groupSimplify.rejectedTopology += result.profile.rejectedTopology;
                stats->groupSimplify.rejectedGeometry += result.profile.rejectedGeometry;
                stats->groupSimplify.rejectedAttributes += result.profile.rejectedAttributes;
                stats->groupSimplify.rejectedBoundary += result.profile.rejectedBoundary;
                stats->groupSimplify.rejectedLocked += result.profile.rejectedLocked;
'''

new = '''        std::vector<uint32_t> next;
        bool createdParent = false;

        // A group the quality gate rejects leaves every member unsimplified, even when only one
        // or two members caused the rejection. Retry each rejected multi-member group as two
        // spatially coherent halves, recursively up to two splits, so a clean subset can still
        // produce a parent. Halves go through the same simplification and gates as a group: this
        // changes the candidate partition, not the quality contract.
        struct GroupDecision {
            std::vector<std::vector<uint32_t>> parentMembers;
            std::vector<GroupBuildResult> parents;
            std::vector<uint32_t> leftover;
        };
        std::vector<GroupDecision> decisions(groups.size());
        struct RetrySlot {
            size_t owner = 0;
            std::vector<uint32_t> members;
        };
        std::vector<RetrySlot> pending;
        constexpr uint32_t MAX_SPLIT_DEPTH = 2;
        auto enqueueSplit = [&](size_t owner, std::vector<uint32_t> const& members,
                                    uint32_t splitDepth, std::vector<RetrySlot>* queue) {
            std::vector<uint32_t> first;
            std::vector<uint32_t> second;
            splitGroupMembers(graph, members, &first, &second);
            for (std::vector<uint32_t>* half: { &first, &second }) {
                if (half->empty()) {
                    continue;
                }
                if (half->size() <= 1 || splitDepth >= MAX_SPLIT_DEPTH) {
                    decisions[owner].leftover.insert(decisions[owner].leftover.end(),
                            half->begin(), half->end());
                } else {
                    queue->push_back({ owner, std::move(*half) });
                }
            }
        };
        for (size_t groupIndex = 0; groupIndex < groups.size(); ++groupIndex) {
            if (results[groupIndex].promoted) {
                continue;
            }
            if (groups[groupIndex].size() <= 2) {
                decisions[groupIndex].leftover = groups[groupIndex];
            } else {
                enqueueSplit(groupIndex, groups[groupIndex], 0, &pending);
            }
        }
        for (uint32_t splitDepth = 0; splitDepth < MAX_SPLIT_DEPTH && !pending.empty();
                ++splitDepth) {
            auto const retryStart = Clock::now();
            std::vector<GroupBuildResult> retryResults(pending.size());
            detail::parallelFor(pending.size(), [&](size_t retryIndex) {
                retryResults[retryIndex] = buildGroup(pending[retryIndex].members);
            });
            if (stats != nullptr) {
                stats->groupSimplifySeconds += secondsSince(retryStart);
            }
            std::vector<RetrySlot> nextPending;
            for (size_t retryIndex = 0; retryIndex < pending.size(); ++retryIndex) {
                RetrySlot& slot = pending[retryIndex];
                GroupBuildResult& retry = retryResults[retryIndex];
                if (retry.promoted) {
                    decisions[slot.owner].parentMembers.push_back(std::move(slot.members));
                    decisions[slot.owner].parents.push_back(std::move(retry));
                } else {
                    enqueueSplit(slot.owner, slot.members, splitDepth + 1, &nextPending);
                }
            }
            pending = std::move(nextPending);
        }

        auto accumulateGroupStats = [&](GroupBuildResult const& result) {
            if (stats == nullptr) {
                return;
            }
''' + stats_block + '''        };
        auto appendParent = [&](std::vector<uint32_t> const& members,
                                    GroupBuildResult& result) {
            if (stats != nullptr) {
                stats->groupSimplifyAccepted += 1;
            }
            appendGeneratedVerticesToGraph(&graph, &graphMesh, result.generatedVertices,
                    levelVertexCount, &generatedLookup, &graphPositions, &graphPositionIds,
                    &result.parent.indices);
            uint32_t const id = uint32_t(graph.nodes.size());
            for (uint32_t member: members) {
                graph.nodes[member].parent = id;
            }
            graph.nodes.push_back(std::move(result.parent));
            next.push_back(id);
            createdParent = true;
        };

        for (size_t groupIndex = 0; groupIndex < groups.size(); ++groupIndex) {
            std::vector<uint32_t> const& members = groups[groupIndex];
            GroupBuildResult& result = results[groupIndex];
            if (!result.candidate) {
                next.insert(next.end(), members.begin(), members.end());
                continue;
            }
            accumulateGroupStats(result);
            if (result.promoted) {
                appendParent(members, result);
            }
            GroupDecision& decision = decisions[groupIndex];
            for (size_t parentIndex = 0; parentIndex < decision.parents.size(); ++parentIndex) {
                accumulateGroupStats(decision.parents[parentIndex]);
                appendParent(decision.parentMembers[parentIndex], decision.parents[parentIndex]);
            }
            next.insert(next.end(), decision.leftover.begin(), decision.leftover.end());
        }'''

lines[start:end] = new.split('\n')
path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
print('patched')

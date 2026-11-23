#!/usr/bin/env python3
"""Conservatively join old verbose gate logs to schema-1 DAG group ledgers.

The join accepts a source-size cohort only when its aggregate 32-bin rejection-mask histogram
matches the verbose records. It assigns individual records only when the mask belongs to exactly
one group in that cohort. This recovers witnesses without assuming that log order matches group
order or guessing among ambiguous groups.
"""

import argparse
import collections
import itertools
import json
import re
from pathlib import Path


REJECT_RE = re.compile(
    r"qualityreject:source=(\d+)target=(\d+)got=(\d+)attempt=(\d+).*?"
    r"normal=([0-9.]+)/([0-9.]+)deguv=([0-9.]+)/([0-9.]+).*?"
    r"worstN=(\d+)/(\d+)worstUv=(\d+)/(\d+).*?"
    r"reason=0x([0-9a-fA-F]+)")


def mask_histogram(records):
    histogram = [0] * 32
    for record in records:
        histogram[int(record["mask"])] += 1
    return histogram


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostics", type=Path)
    parser.add_argument("lod_graph", type=Path)
    parser.add_argument("quality_log", type=Path)
    parser.add_argument("--max-normal-deg", type=float, default=35.0)
    parser.add_argument("--max-uv-error", type=float, default=0.10)
    parser.add_argument("--out", type=Path, default=Path(
        "out/quality-witness-log-join/audit.json"))
    args = parser.parse_args()

    diagnostics = json.loads(args.diagnostics.read_text(encoding="utf-8"))
    graph_data = json.loads(args.lod_graph.read_text(encoding="utf-8"))
    graph_nodes = {int(node["id"]): node for node in graph_data["dag"]}
    text = args.quality_log.read_text(encoding="utf-16", errors="replace")
    records_by_source = collections.defaultdict(list)
    all_records = []
    for block in re.split(r"(?=quality reject: source=)", text):
        if not block.startswith("quality reject: source="):
            continue
        normalized = "".join(block.split())
        match = REJECT_RE.search(normalized)
        if not match:
            continue
        (source, target, got, attempt, max_normal, mean_normal, max_uv, mean_uv,
         normal_v, normal_t, uv_v, uv_t, mask) = match.groups()
        record = {
            "source": int(source), "target": int(target), "got": int(got),
            "attempt": int(attempt), "maxNormalDegrees": float(max_normal),
            "meanNormalDegrees": float(mean_normal), "maxUvError": float(max_uv),
            "meanUvError": float(mean_uv), "worstNormalVertex": int(normal_v),
            "worstNormalTriangle": int(normal_t), "worstUvVertex": int(uv_v),
            "worstUvTriangle": int(uv_t), "mask": int(mask, 16),
        }
        records_by_source[record["source"]].append(record)
        all_records.append(record)

    groups = [(index, g) for index, g in enumerate(diagnostics["groups"])
              if int(g.get("trial", 0)) == 0]
    groups_by_source = collections.defaultdict(list)
    for group_index, group in groups:
        groups_by_source[len(group["inputIndices"])].append((group_index, group))

    matched = []
    cohort_checks = []
    assigned_records = collections.defaultdict(list)
    assigned_histograms = collections.defaultdict(lambda: [0] * 32)
    unique_assignment_record_count = 0
    for source, source_groups in groups_by_source.items():
        expected = [0] * 32
        for _, group in source_groups:
            for i, count in enumerate(group.get("rejectedMaskCounts", [0] * 32)):
                expected[i] += int(count)
        cohort_records = records_by_source.get(source, [])
        observed = mask_histogram(cohort_records)
        cohort_match = expected == observed
        unique_assigned = 0
        ambiguous = 0
        if cohort_match:
            for mask in range(32):
                owners = [group_index for group_index, group in source_groups
                          if int(group.get("rejectedMaskCounts", [0] * 32)[mask]) > 0]
                mask_records = [record for record in cohort_records
                                if int(record["mask"]) == mask]
                if len(owners) == 1:
                    group_index = owners[0]
                    assigned_records[group_index].extend(mask_records)
                    assigned_histograms[group_index][mask] += len(mask_records)
                    unique_assigned += len(mask_records)
                elif owners:
                    ambiguous += len(mask_records)
        unique_assignment_record_count += unique_assigned
        cohort_checks.append({"sourceIndexCount": source,
                              "groupCount": len(source_groups),
                              "expectedRecords": sum(expected),
                              "observedRecords": sum(observed),
                              "histogramMatches": cohort_match,
                              "uniquelyAssignedRecords": unique_assigned,
                              "ambiguousRecords": ambiguous})
        if not cohort_match:
            continue

    groups_by_index = dict(groups)
    for group_index, records in assigned_records.items():
        group = groups_by_index[group_index]
        source = len(group["inputIndices"])
        source_ids = set(map(int, group["inputIndices"]))
        member_ids = list(map(int, group["members"]))
        # The diagnostic input stream is assembled by concatenating each member's index array
        # in `members` order. The graph JSON stores each child's triangle count, so these slices
        # recover child ownership without relying on the verbose log's record ordering.
        child_of_vertex = collections.defaultdict(list)
        offset = 0
        for member_id in member_ids:
            member_index_count = int(graph_nodes[member_id]["tri"]) * 3
            member_indices = group["inputIndices"][offset:offset + member_index_count]
            if len(member_indices) != member_index_count:
                raise ValueError(f"group member slice is truncated: {member_id}")
            for vertex in set(map(int, member_indices)):
                child_of_vertex[vertex].append(member_id)
            offset += member_index_count
        if offset != len(group["inputIndices"]):
            raise ValueError(f"member triangle counts do not cover group input: {source}")
        invalid_witness_vertices = 0
        valid_normal = 0
        valid_uv = 0
        unique_child_normal = 0
        unique_child_uv = 0
        multi_child_witnesses = 0
        witness_counts_by_child = collections.defaultdict(lambda: {"normal": 0, "uv": 0})
        attribute_witness_counts_by_child = collections.defaultdict(
            lambda: {"normal": 0, "uv": 0})
        attribute_witness_pairs = collections.Counter()
        attribute_same_child_records = 0
        attribute_cross_child_records = 0
        attribute_ambiguous_pair_records = 0
        attribute_gate_causes = collections.Counter()
        attribute_rejection_records = sum(bool(int(record["mask"]) & (1 << 2))
                                          for record in records)
        attribute_unique_witnesses = 0
        attribute_multi_child_witnesses = 0
        for record in records:
            normal_owners = []
            uv_owners = []
            for field, valid_counter in (("worstNormalVertex", "normal"),
                                          ("worstUvVertex", "uv")):
                vertex = int(record[field])
                if vertex == 0xFFFFFFFF:
                    continue
                if vertex not in source_ids:
                    invalid_witness_vertices += 1
                    continue
                if valid_counter == "normal":
                    valid_normal += 1
                else:
                    valid_uv += 1
                owners = child_of_vertex.get(vertex, [])
                if valid_counter == "normal":
                    normal_owners = owners
                else:
                    uv_owners = owners
                if len(owners) == 1:
                    witness_counts_by_child[owners[0]][valid_counter] += 1
                    if valid_counter == "normal":
                        unique_child_normal += 1
                    else:
                        unique_child_uv += 1
                elif len(owners) > 1:
                    multi_child_witnesses += 1
            if int(record["mask"]) & (1 << 2):
                normal_fail = (record["maxNormalDegrees"] > args.max_normal_deg + 0.01 or
                               record["meanNormalDegrees"] > args.max_normal_deg * 0.5 + 0.01)
                uv_fail = (record["maxUvError"] > args.max_uv_error * 8.0 + 0.0001 or
                           record["meanUvError"] > args.max_uv_error + 0.0001)
                cause = ("both" if normal_fail and uv_fail else
                         "normal_only" if normal_fail else
                         "uv_only" if uv_fail else "rounded_metrics_ambiguous")
                attribute_gate_causes[cause] += 1
                for attribute, fails, owners in (("normal", normal_fail, normal_owners),
                                                  ("uv", uv_fail, uv_owners)):
                    if not fails:
                        continue
                    if len(owners) == 1:
                        attribute_witness_counts_by_child[owners[0]][attribute] += 1
                        attribute_unique_witnesses += 1
                    elif len(owners) > 1:
                        attribute_multi_child_witnesses += 1
                if normal_fail and uv_fail:
                    if len(normal_owners) == 1 and len(uv_owners) == 1:
                        if normal_owners[0] == uv_owners[0]:
                            attribute_same_child_records += 1
                        else:
                            attribute_cross_child_records += 1
                            pair = tuple(sorted((normal_owners[0], uv_owners[0])))
                            attribute_witness_pairs[pair] += 1
                    else:
                        attribute_ambiguous_pair_records += 1
        expected_group_histogram = list(map(int, group.get("rejectedMaskCounts", [0] * 32)))
        assigned_group_histogram = assigned_histograms[group_index]
        matched.append({
            "diagnosticsGroupIndex": group_index,
            "level": int(group["level"]), "members": member_ids,
            "promoted": bool(group["promoted"]),
            "sourceIndexCount": source, "rejectionRecords": len(records),
            "fullyAttributable": assigned_group_histogram == expected_group_histogram,
            "expectedMaskHistogram": expected_group_histogram,
            "assignedMaskHistogram": assigned_group_histogram,
            "worstNormalWitnessesInsideGroupInput": valid_normal,
            "worstUvWitnessesInsideGroupInput": valid_uv,
            "worstNormalWitnessesUniqueChild": unique_child_normal,
            "worstUvWitnessesUniqueChild": unique_child_uv,
            "witnessesOnMultipleChildren": multi_child_witnesses,
            "witnessesOutsideGroupInput": invalid_witness_vertices,
            "attributeRejectionRecords": attribute_rejection_records,
            "attributeUniqueChildWitnesses": attribute_unique_witnesses,
            "attributeMultiChildWitnesses": attribute_multi_child_witnesses,
            "attributeSameChildWitnessRecords": attribute_same_child_records,
            "attributeCrossChildWitnessRecords": attribute_cross_child_records,
            "attributeAmbiguousPairRecords": attribute_ambiguous_pair_records,
            "attributeGateFailureCauses": dict(attribute_gate_causes),
            "attributeWitnessPairs": {f"{first},{second}": count
                                       for (first, second), count in
                                       attribute_witness_pairs.items()},
            "witnessCountsByChild": {str(child): counts
                                     for child, counts in witness_counts_by_child.items()},
            "attributeWitnessCountsByChild": {
                str(child): counts
                for child, counts in attribute_witness_counts_by_child.items()},
            "records": records,
        })

    # Compare recovered dominant attribute witnesses with existing same-build spatial retry
    # outcomes. This is diagnostic only: the split choice was not changed by the witness.
    split_outcomes = []
    groups_by_level = collections.defaultdict(list)
    for group_index, group in groups:
        groups_by_level[int(group["level"])].append((group_index, group))
    for row in matched:
        weights = {int(child): int(counts["normal"]) + int(counts["uv"])
                   for child, counts in row["attributeWitnessCountsByChild"].items()}
        if not weights:
            continue
        parent_members = set(map(int, row["members"]))
        children = []
        for group_index, candidate in groups_by_level[row["level"]]:
            candidate_members = frozenset(map(int, candidate["members"]))
            if group_index == row["diagnosticsGroupIndex"] or not candidate_members:
                continue
            if candidate_members < parent_members:
                children.append((candidate_members, bool(candidate["promoted"])))
        partitions = {}
        for i, (first_members, first_promoted) in enumerate(children):
            for second_members, second_promoted in children[i + 1:]:
                if first_members.isdisjoint(second_members) and \
                        first_members | second_members == parent_members:
                    canonical = tuple(sorted((tuple(sorted(first_members)),
                                              tuple(sorted(second_members)))))
                    partitions[canonical] = (first_promoted, second_promoted,
                                             first_members, second_members)
        if len(partitions) != 1:
            continue
        partition = next(iter(partitions.values()))
        first_promoted, second_promoted, first_members, second_members = partition
        dominant_child = max(weights, key=weights.get)
        if dominant_child in first_members:
            witness_half_promoted, other_half_promoted = first_promoted, second_promoted
        elif dominant_child in second_members:
            witness_half_promoted, other_half_promoted = second_promoted, first_promoted
        else:
            continue
        witness_pairs = {tuple(map(int, key.split(","))): int(count)
                         for key, count in row["attributeWitnessPairs"].items()}
        total_pair_weight = sum(witness_pairs.values())
        cut_pair_weight = sum(count for pair, count in witness_pairs.items()
                              if (pair[0] in first_members) != (pair[1] in first_members))
        # Offline partition upper bound: among cardinality-balanced bipartitions, maximize
        # witness-pair separation, then minimize a shared-vertex boundary proxy and triangle
        # imbalance. This does not rebuild either half or establish that the witnesses are causal.
        shared_vertex_costs = collections.Counter()
        for owners in child_of_vertex.values():
            if len(owners) > 1:
                for i, first in enumerate(sorted(owners)):
                    for second in sorted(owners)[i + 1:]:
                        shared_vertex_costs[(first, second)] += 1

        def partition_cost(left):
            right = parent_members - left
            separated = sum(count for (first, second), count in witness_pairs.items()
                            if (first in left) != (second in left))
            boundary = sum(count for (first, second), count in shared_vertex_costs.items()
                           if (first in left) != (second in left))
            left_triangles = sum(int(graph_nodes[child]["tri"]) for child in left)
            right_triangles = sum(int(graph_nodes[child]["tri"]) for child in right)
            imbalance = abs(left_triangles - right_triangles)
            return (separated, -boundary, -imbalance), boundary, imbalance

        best_partition_score = None
        best_partition_cut = 0
        best_partition_boundary = 0
        best_partition_imbalance = 0
        ordered_members = sorted(parent_members)
        left_sizes = {len(parent_members) // 2, (len(parent_members) + 1) // 2}
        for left_size in left_sizes:
            for subset in itertools.combinations(ordered_members[1:], left_size - 1):
                left = {ordered_members[0], *subset}
                if len(left) != left_size or len(left) == len(parent_members):
                    continue
                score, boundary, imbalance = partition_cost(left)
                if best_partition_score is None or score > best_partition_score:
                    best_partition_score = score
                    best_partition_cut = score[0]
                    best_partition_boundary = boundary
                    best_partition_imbalance = imbalance
        split_outcomes.append({
            "diagnosticsGroupIndex": row["diagnosticsGroupIndex"],
            "members": row["members"], "dominantWitnessChild": dominant_child,
            "dominantWitnessCount": weights[dominant_child],
            "witnessHalfPromoted": witness_half_promoted,
            "otherHalfPromoted": other_half_promoted,
            "attributeCrossChildPairWeight": total_pair_weight,
            "attributePairWeightCutBySpatialSplit": cut_pair_weight,
            "attributePairWeightCutByBestBalancedPartition": best_partition_cut,
            "sharedVertexCostAtSpatialSplit": partition_cost(first_members)[1],
            "sharedVertexCostAtBestBalancedPartition": best_partition_boundary,
            "triangleImbalanceAtSpatialSplit": partition_cost(first_members)[2],
            "triangleImbalanceAtBestBalancedPartition": best_partition_imbalance,
        })

    output = {
        "diagnosticsSchema": diagnostics.get("schema"),
        "qualityLogRecordCount": len(all_records),
        "trialZeroGroupCount": len(groups),
        "groupsWithUnambiguousRecords": len(matched),
        "fullyAttributableGroups": sum(bool(row["fullyAttributable"]) for row in matched),
        "partiallyAttributableGroups": sum(not row["fullyAttributable"] for row in matched),
        "unambiguouslyAssignedRecordCount": unique_assignment_record_count,
        "matchedRejectionRecordCount": sum(row["rejectionRecords"] for row in matched),
        "matchedWitnessesOutsideGroupInput": sum(
            row["witnessesOutsideGroupInput"] for row in matched),
        "matchedNormalWitnessesInsideGroupInput": sum(
            row["worstNormalWitnessesInsideGroupInput"] for row in matched),
        "matchedUvWitnessesInsideGroupInput": sum(
            row["worstUvWitnessesInsideGroupInput"] for row in matched),
        "matchedNormalWitnessesUniqueChild": sum(
            row["worstNormalWitnessesUniqueChild"] for row in matched),
        "matchedUvWitnessesUniqueChild": sum(
            row["worstUvWitnessesUniqueChild"] for row in matched),
        "matchedWitnessesOnMultipleChildren": sum(
            row["witnessesOnMultipleChildren"] for row in matched),
        "matchedAttributeRejectionRecords": sum(
            row["attributeRejectionRecords"] for row in matched),
        "matchedAttributeUniqueChildWitnesses": sum(
            row["attributeUniqueChildWitnesses"] for row in matched),
        "matchedAttributeMultiChildWitnesses": sum(
            row["attributeMultiChildWitnesses"] for row in matched),
        "matchedAttributeSameChildWitnessRecords": sum(
            row["attributeSameChildWitnessRecords"] for row in matched),
        "matchedAttributeCrossChildWitnessRecords": sum(
            row["attributeCrossChildWitnessRecords"] for row in matched),
        "matchedAttributeAmbiguousPairRecords": sum(
            row["attributeAmbiguousPairRecords"] for row in matched),
        "attributeGateFailureCauses": dict(sum(
            (collections.Counter(row["attributeGateFailureCauses"]) for row in matched),
            collections.Counter())),
        "matchedGroups": matched,
        "uniqueComplementarySpatialRetryPairs": len(split_outcomes),
        "spatialRetryWitnessOutcomeChecks": split_outcomes,
        "sourceCohortChecks": cohort_checks,
        "warning": "Only source-size cohorts with exact aggregate mask-histogram matches are "
                   "used, and individual rejection records are assigned only when their mask "
                   "occurs in exactly one group in that cohort. "
                   "Child ownership is reconstructed by slicing the diagnostic inputIndices in "
                   "member order using each graph node's triangle count. These remain historical "
                   "diagnostics, not a held-out algorithm result.",
    }
    concentration = []
    for row in matched:
        counts = [int(values["normal"]) + int(values["uv"])
                  for values in row["attributeWitnessCountsByChild"].values()]
        total = sum(counts)
        if total:
            concentration.append(max(counts) / total)
    output["attributeWitnessTopChildShare"] = {
        "groupsWithAttributeWitnesses": len(concentration),
        "mean": (sum(concentration) / len(concentration)) if concentration else None,
        "median": (sorted(concentration)[len(concentration) // 2]
                   if concentration else None),
        "groupsAtLeastHalf": sum(value >= 0.5 for value in concentration),
    }
    output["spatialRetryWitnessSummary"] = {
        "witnessHalfPromoted": sum(row["witnessHalfPromoted"]
                                    for row in split_outcomes),
        "otherHalfPromoted": sum(row["otherHalfPromoted"]
                                  for row in split_outcomes),
        "bothPromoted": sum(row["witnessHalfPromoted"] and row["otherHalfPromoted"]
                             for row in split_outcomes),
        "neitherPromoted": sum(not row["witnessHalfPromoted"] and
                                not row["otherHalfPromoted"] for row in split_outcomes),
        "groupsWithCrossChildAttributePairs": sum(
            row["attributeCrossChildPairWeight"] > 0 for row in split_outcomes),
        "totalCrossChildPairWeight": sum(
            row["attributeCrossChildPairWeight"] for row in split_outcomes),
        "crossChildPairWeightCutBySplit": sum(
            row["attributePairWeightCutBySpatialSplit"] for row in split_outcomes),
        "crossChildPairWeightCutByBestBalancedPartition": sum(
            row["attributePairWeightCutByBestBalancedPartition"] for row in split_outcomes),
        "spatialSplitSharedVertexCost": sum(
            row["sharedVertexCostAtSpatialSplit"] for row in split_outcomes),
        "bestBalancedPartitionSharedVertexCost": sum(
            row["sharedVertexCostAtBestBalancedPartition"] for row in split_outcomes),
        "warning": "These are captured spatial splits; witness locations did not choose the split.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items()
                      if key not in ("matchedGroups", "sourceCohortChecks",
                                     "spatialRetryWitnessOutcomeChecks")}, indent=2))


if __name__ == "__main__":
    main()

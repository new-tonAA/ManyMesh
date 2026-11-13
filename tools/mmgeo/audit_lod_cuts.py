#!/usr/bin/env python3
"""Count full-view cuts and exhaustively check assembled face counts on small MMLG v7 graphs."""

import argparse
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import struct


def audit(path, limit):
    data = path.read_bytes()
    magic, version, count, root_count, leaf_count, _, base, vertices = struct.unpack_from(
        '<4s5IQI', data)
    if (magic, version) != (b'MMLG', 7):
        raise ValueError('expected MMLG v7')
    roots = struct.unpack_from(f'<{root_count}I', data, 36)
    cursor = 36 + 4 * (root_count + leaf_count)
    generated, = struct.unpack_from('<I', data, cursor)
    cursor += 4 + 40 * generated
    position_count, = struct.unpack_from('<I', data, cursor)
    if position_count != vertices:
        raise ValueError('missing canonical position IDs')
    cursor += 4
    positions = struct.unpack_from(f'<{vertices}I', data, cursor)
    cursor += 4 * vertices
    offsets = struct.unpack_from(f'<{count + 1}Q', data, cursor)
    if offsets[0] != cursor + 8 * (count + 1) or offsets[-1] != len(data):
        raise ValueError('invalid node table')

    children = []
    triangles = []
    ways = []
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        nchildren, nindices = struct.unpack_from('<II', data, start + 16)
        payload = start + 184
        if nindices % 3 or payload + 4 * (nchildren + nindices) != end:
            raise ValueError('invalid node record')
        ids = struct.unpack_from(f'<{nchildren}I', data, payload)
        if any(child >= index for child in ids):
            raise ValueError('expected children before parents')
        children.append(ids)
        triangles.append(nindices // 3)
        subtotal = 1
        for child in ids:
            subtotal = min(limit + 1, subtotal * ways[child])
        ways.append(min(limit + 1, 1 + subtotal) if ids else 1)

    total = 1
    for root in roots:
        total = min(limit + 1, total * ways[root])

    @lru_cache(maxsize=None)
    def faces(node):
        start = offsets[node] + 184 + 4 * len(children[node])
        indices = struct.unpack_from(f'<{3 * triangles[node]}I', data, start)
        # Match selectionFromCut: reject repeated raw indices, then deduplicate welded faces.
        return {tuple(sorted(positions[i] for i in face))
                for face in zip(indices[::3], indices[1::3], indices[2::3])
                if len(set(face)) == 3}

    def assembled(cut):
        return len(set().union(*(faces(node) for node in cut)))

    def cuts(node):
        yield (node,)
        if children[node]:
            for parts in product(*(cuts(child) for child in children[node])):
                yield tuple(node for part in parts for node in part)

    result = dict(baseTriangles=base, roots=len(roots),
                  rootRawTriangles=sum(triangles[root] for root in roots),
                  rootAssembledTriangles=assembled(roots),
                  enumeratedCuts=0, cutCountLowerBound=total)
    if total <= limit:
        best = result['rootAssembledTriangles']
        witness = roots
        for parts in product(*(cuts(root) for root in roots)):
            cut = tuple(node for part in parts for node in part)
            value = assembled(cut)
            if value < best:
                best, witness = value, cut
            result['enumeratedCuts'] += 1
        result.update(minAssembledTriangles=best, minimumCut=witness)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('graphs', nargs='+', type=Path)
    parser.add_argument('--max-cuts', type=int, default=10_000)
    args = parser.parse_args()
    if args.max_cuts < 1:
        parser.error('--max-cuts must be positive')
    print(json.dumps({str(path): audit(path, args.max_cuts) for path in args.graphs}, indent=2))


if __name__ == '__main__':
    main()

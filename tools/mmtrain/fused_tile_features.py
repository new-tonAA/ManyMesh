"""Single-pass CPU implementation of the raster tile statistics."""

from numba import njit
import numpy as np

from tile_refinement import TILE_SIZE


@njit
def fused_tile_features(color, depth):
    height, width = color.shape
    columns = width // TILE_SIZE
    output = np.empty((height // TILE_SIZE * columns, 7), np.float32)
    count = TILE_SIZE * TILE_SIZE
    depth_limit = np.float32(0.04)
    for tile_y in range(height // TILE_SIZE):
        for tile_x in range(columns):
            coverage = silhouette = contrast = slope = steps = intensity = squares = 0.0
            for y in range(tile_y * TILE_SIZE, (tile_y + 1) * TILE_SIZE):
                for x in range(tile_x * TILE_SIZE, (tile_x + 1) * TILE_SIZE):
                    current = color[y, x]
                    z = depth[y, x]
                    covered = np.isfinite(z)
                    coverage += covered
                    intensity += current
                    squares += current * current
                    for dy, dx in ((-1, 0), (0, -1)):
                        if y + dy < 0 or x + dx < 0:
                            continue
                        neighbor = depth[y + dy, x + dx]
                        neighbor_covered = np.isfinite(neighbor)
                        silhouette += covered != neighbor_covered
                        contrast += abs(current - color[y + dy, x + dx])
                        if covered and neighbor_covered:
                            change = abs(z - neighbor)
                            slope += min(change, depth_limit)
                            steps += change > depth_limit
            row = output[tile_y * columns + tile_x]
            mean = intensity / count
            row[0] = coverage / count
            row[1] = silhouette / count
            row[2] = contrast / count
            row[3] = slope / count
            row[4] = steps / count
            row[5] = mean
            row[6] = max(0.0, squares / count - mean * mean)
    return output

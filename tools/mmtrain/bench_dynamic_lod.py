"""Measure fixed-budget resident LOD switches on moving, non-overlapping instances."""

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import time

import numpy as np
import wgpu
from wgpu.backends.wgpu_native import lib
from skimage.metrics import structural_similarity

from bench_component_gpu import load_export, projection_matrix, select_adapter


SIDE = 4
COUNT = SIDE * SIDE
BINS = 12
POLICIES = ("area", "area-hysteresis", "area-switch-cost", "direction", "direction-hysteresis",
            "direction-switch-cost", "scale-direction", "scale-direction-switch-cost")
MARGINS = (0.07, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.25, 1.50, 2.00)
SHADER = """
struct Transform {
    view_projection: mat4x4f,
    cell: u32,
};
struct VertexOut {
    @builtin(position) clip: vec4f,
    @location(0) light: f32,
    @location(1) @interpolate(flat) cell: u32,
};
@group(0) @binding(0) var<storage, read> poses: array<Transform>;
override tile_width: u32;
override tile_height: u32;

@vertex fn vertex_main(@location(0) point: vec3f, @location(1) normal: vec3f,
                       @builtin(instance_index) instance: u32) -> VertexOut {
    let pose = poses[instance];
    let light = 0.20 + 0.75 * clamp(dot(normal, vec3f(0.36, 0.80, 0.48)), 0.0, 1.0);
    return VertexOut(pose.view_projection * vec4f(point, 1.0), light, pose.cell);
}
@fragment fn fragment_main(in: VertexOut) -> @location(0) vec4f {
    let pixel = vec2u(in.clip.xy);
    let cell = pixel.y / tile_height * 4u + pixel.x / tile_width;
    if cell != in.cell { discard; }
    return vec4f(vec3f(in.light), 1.0);
}
"""


def trajectory(width, height, frames, path):
    index = np.arange(COUNT)
    phase = index * 2.3999632297
    orientation = index * (2 * np.pi / COUNT)
    tile = np.broadcast_to(np.eye(4), (COUNT, 4, 4)).copy()
    tile[:, 0, 0] = tile[:, 1, 1] = 1 / SIDE
    tile[:, 0, 3] = 2 * (index % SIDE + 0.5) / SIDE - 1
    tile[:, 1, 3] = 1 - 2 * (index // SIDE + 0.5) / SIDE
    result = []
    for t in np.arange(frames) / frames:
        if path == 0:
            yaw, elevation = 2 * np.pi * t, 0.16 + 0.12 * np.sin(2 * np.pi * t)
        else:
            yaw = (0.3 + 1.8 * np.sin(1.5 * np.pi * t + 0.7 * path)) * (-1)**path
            elevation = 0.25 + 0.24 * np.sin(2 * np.pi * t + path)
        radius = 3.4 + 0.12 * np.sin(2 * np.pi * t + path)
        eye = radius * np.array([np.sin(yaw) * np.cos(elevation), np.sin(elevation),
                                 np.cos(yaw) * np.cos(elevation)])
        scale = 0.73 + 0.24 * np.sin(2 * np.pi * t + phase + path * 0.33)
        c, s = np.cos(orientation), np.sin(orientation)
        model = np.broadcast_to(np.eye(4), (COUNT, 4, 4)).copy()
        model[:, 0, 0] = model[:, 2, 2] = c * scale
        model[:, 2, 0] = -s * scale
        model[:, 0, 2] = s * scale
        model[:, 1, 1] = scale
        matrices = tile @ projection_matrix(width, height, eye).T @ model
        result.append((np.ascontiguousarray(matrices.transpose(0, 2, 1), dtype=np.float32),
                       (scale / radius)**2, (yaw - orientation) % (2 * np.pi)))
    return result


def calibrate(poses, measured):
    size_centers = np.quantile(np.concatenate([np.sqrt(pose[1]) for pose in poses]),
                               (1/6, .5, 5/6))
    pixel_density = np.zeros((len(size_centers), BINS))
    surface = np.zeros_like(pixel_density)
    for (_, area, angle), error in zip(poses, measured, strict=True):
        bin_id = np.floor(angle / (2 * np.pi) * BINS).astype(int) % BINS
        size_bin = np.argmin(np.abs(np.sqrt(area)[:, None] - size_centers), axis=1)
        np.add.at(pixel_density, (size_bin, bin_id), error)
        np.add.at(surface, (size_bin, bin_id), area)
    column = surface.sum(axis=0)
    if np.any(column <= 0):
        raise ValueError("Insufficient turntable data for directional interpolation")
    direction = pixel_density.sum(axis=0) / column
    prior = column * 0.04
    by_size = (pixel_density + direction * prior) / (surface + prior)
    return direction, by_size, size_centers


def choose(policy, area, angle, table, keep, previous, old_benefit, margin=None):
    if policy.startswith("area"):
        benefit = area
    else:
        direction, by_size, centers = table
        offset = angle * BINS / (2 * np.pi) - 0.5
        floor = np.floor(offset)
        left = floor.astype(int) % BINS
        right = (left + 1) % BINS
        t = offset - floor
        if policy.startswith("scale"):
            sizes = np.sqrt(area)
            high = np.clip(np.searchsorted(centers, sizes), 1, len(centers) - 1)
            low = high - 1
            weight = np.clip((sizes - centers[low]) / (centers[high] - centers[low]), 0, 1)
            lower = (1 - t) * by_size[low, left] + t * by_size[low, right]
            upper = (1 - t) * by_size[high, left] + t * by_size[high, right]
            benefit = area * ((1 - weight) * lower + weight * upper)
        else:
            benefit = area * ((1 - t) * direction[left] + t * direction[right])
    score = benefit
    if previous is not None:
        if policy.endswith("hysteresis"):
            weight = 0.30 if margin is None else margin
            score = benefit + previous * np.median(benefit) * weight
        elif policy.endswith("switch-cost"):
            # Promotion removes the previous residual. Demotion introduces the current one.
            weight = 0.35 if margin is None else margin
            score = benefit + weight * np.where(previous, benefit, -old_benefit)
    selected = np.zeros(COUNT, dtype=bool)
    selected[np.argsort(-score, kind="stable")[:keep]] = True
    return selected, benefit


def cross_validated_ranker(poses, errors, keep):
    rankers = ("area", "direction", "scale-direction")
    scores = dict.fromkeys(rankers, 0.0)
    for test in np.array_split(np.arange(len(poses)), 4):
        train = np.setdiff1d(np.arange(len(poses)), test)
        fit = calibrate([poses[i] for i in train], errors[train])
        for index in test:
            _, area, angle = poses[index]
            for name in rankers:
                fine, _ = choose(name, area, angle, fit, keep, None, None)
                scores[name] += float(errors[index][~fine].sum())
    best = min(rankers, key=lambda name: scores[name])
    chosen = best if scores[best] < .997 * scores["area"] else "area"
    return chosen, scores


def normalized_asset_error(errors):
    mean_error = float(np.mean(errors.sum(axis=1)))
    if not math.isfinite(mean_error) or mean_error <= 0:
        raise ValueError("Asset training error must have a finite positive mean")
    return errors / mean_error


def profile_objective_errors(color_errors, silhouette_errors, objective):
    if objective == "color-sse":
        return color_errors
    if objective == "silhouette-xor":
        return silhouette_errors
    if objective == "balanced-color-silhouette":
        return 0.5 * (normalized_asset_error(color_errors) +
                      normalized_asset_error(silhouette_errors))
    raise ValueError(f"Unknown profile objective: {objective}")


def shared_profile(poses, errors_by_asset, excluded_asset):
    profile_poses, profile_errors = [], []
    for name, errors in errors_by_asset.items():
        if name == excluded_asset:
            continue
        profile_poses.extend(poses)
        profile_errors.append(normalized_asset_error(errors))
    if not profile_errors:
        raise ValueError("A shared profile needs at least one training asset")
    return calibrate(profile_poses, np.concatenate(profile_errors, axis=0))


def cross_validated_ranker_by_asset(poses, errors_by_asset, keep):
    """Choose one profile family using leave-one-asset-out training folds."""
    rankers = ("area", "direction", "scale-direction")
    scores = dict.fromkeys(rankers, 0.0)
    for held_out, errors in errors_by_asset.items():
        fit = shared_profile(poses, errors_by_asset, held_out)
        errors = normalized_asset_error(errors)
        for index, pose in enumerate(poses):
            _, area, angle = pose
            for name in rankers:
                fine, _ = choose(name, area, angle, fit, keep, None, None)
                scores[name] += float(errors[index][~fine].sum())
    best = min(rankers, key=lambda name: scores[name])
    chosen = best if scores[best] < .997 * scores["area"] else "area"
    return chosen, scores


class Scene:
    def __init__(self, device, width, height):
        self.device, self.queue = device, device.queue
        self.width, self.height = width, height
        self.period = lib.wgpuQueueGetTimestampPeriod(self.queue._internal)
        if not math.isfinite(self.period) or self.period <= 0:
            raise RuntimeError("Invalid timestamp period")
        color_usage = wgpu.TextureUsage.RENDER_ATTACHMENT
        self.output = device.create_texture(size=(width, height, 1), format="rgba8unorm",
                                            usage=color_usage | wgpu.TextureUsage.COPY_SRC)
        self.output_view = self.output.create_view()
        self.depth = device.create_texture(size=(width, height, 1), format="depth32float",
                                           usage=color_usage).create_view()
        self.buffer = device.create_buffer(size=COUNT * 80,
                                          usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST)
        shader = device.create_shader_module(code=SHADER)
        self.pipeline = device.create_render_pipeline(
            layout="auto",
            vertex={"module": shader, "entry_point": "vertex_main", "buffers": [{
                "array_stride": 24, "attributes": [
                    {"format": "float32x3", "offset": 0, "shader_location": 0},
                    {"format": "float32x3", "offset": 12, "shader_location": 1}]}]},
            fragment={"module": shader, "entry_point": "fragment_main",
                      "constants": {"tile_width": width // SIDE, "tile_height": height // SIDE},
                      "targets": [{"format": "rgba8unorm"}]},
            depth_stencil={"format": "depth32float", "depth_write_enabled": True,
                           "depth_compare": "less"})
        self.bind = device.create_bind_group(layout=self.pipeline.get_bind_group_layout(0),
                                             entries=[{"binding": 0, "resource": {"buffer": self.buffer}}])

    def draw(self, meshes, pose, selected, query=None, frame=0):
        matrices = pose[0]
        order = np.argsort(selected, kind="stable")
        payload = np.zeros((COUNT, 20), dtype=np.float32)
        payload[:, :16] = matrices[order].reshape(COUNT, 16)
        payload.view(np.uint32)[:, 16] = order
        self.queue.write_buffer(self.buffer, 0, payload)
        encoder = self.device.create_command_encoder()
        stamps = ({"query_set": query, "beginning_of_pass_write_index": frame * 2,
                   "end_of_pass_write_index": frame * 2 + 1} if query is not None else None)
        rendering = encoder.begin_render_pass(
            color_attachments=[{"view": self.output_view, "load_op": "clear", "store_op": "store",
                                "clear_value": (0, 0, 0, 1)}],
            depth_stencil_attachment={"view": self.depth, "depth_load_op": "clear",
                                      "depth_clear_value": 1.0, "depth_store_op": "discard"},
            timestamp_writes=stamps)
        rendering.set_pipeline(self.pipeline)
        rendering.set_bind_group(0, self.bind)
        first = 0
        high = int(selected.sum())
        for (vertices, indices, count), instances in zip(meshes, (COUNT - high, high), strict=True):
            if instances:
                rendering.set_vertex_buffer(0, vertices)
                rendering.set_index_buffer(indices, "uint32")
                rendering.draw_indexed(count, instances, 0, 0, first)
            first += instances
        rendering.end()
        self.queue.submit([encoder.finish()])

    def capture(self, meshes, pose, selected):
        self.draw(meshes, pose, selected)
        raw = self.queue.read_texture(
            {"texture": self.output},
            {"bytes_per_row": self.width * 4, "rows_per_image": self.height},
            (self.width, self.height, 1))
        return np.frombuffer(raw, dtype=np.uint8).reshape(self.height, self.width, 4)[..., 0].copy()

    def measure(self, meshes, poses, table, keep, policy):
        samples = len(poses)
        query = self.device.create_query_set(type="timestamp", count=2 * samples)
        resolved = self.device.create_buffer(size=16 * samples,
                                             usage=wgpu.BufferUsage.QUERY_RESOLVE | wgpu.BufferUsage.COPY_SRC)
        previous = old_benefit = None
        for pose in poses[:8]:
            selected, benefit = choose(policy, pose[1], pose[2], table, keep, previous, old_benefit)
            self.draw(meshes, pose, selected)
            previous, old_benefit = selected, benefit
        previous = old_benefit = None
        cpu, selector = [], []
        for frame, pose in enumerate(poses):
            start = time.perf_counter()
            _, area, angle = pose
            selected, benefit = choose(policy, area, angle, table, keep, previous, old_benefit)
            after_choice = time.perf_counter()
            self.draw(meshes, pose, selected, query, frame)
            completed = time.perf_counter()
            cpu.append((completed - start) * 1000)
            selector.append((after_choice - start) * 1000)
            previous, old_benefit = selected, benefit
        encoder = self.device.create_command_encoder()
        encoder.resolve_query_set(query, 0, 2 * samples, resolved, 0)
        self.queue.submit([encoder.finish()])
        ticks = np.frombuffer(self.queue.read_buffer(resolved), dtype="<u8").reshape(samples, 2)
        if np.any(ticks[:, 1] <= ticks[:, 0]):
            raise RuntimeError("GPU timestamp ordering failure")
        raster = (ticks[:, 1] - ticks[:, 0]) * (self.period / 1e6)
        query.destroy()
        resolved.destroy()
        return {"gpuMs": raster.tolist(), "cpuMs": cpu, "selectorMs": selector}


def error_table(scene, meshes, poses, image_stride=None):
    errors = []
    silhouette_errors = []
    image_pairs = []
    all_low = np.zeros(COUNT, dtype=bool)
    all_high = np.ones(COUNT, dtype=bool)
    for index, pose in enumerate(poses):
        lower = scene.capture(meshes, pose, all_low)
        upper = scene.capture(meshes, pose, all_high)
        if not np.any(upper):
            raise RuntimeError("Reference image is empty")
        delta = np.square((lower.astype(np.float32) - upper) / 255,
                          dtype=np.float64).reshape(SIDE, scene.height // SIDE,
                                                    SIDE, scene.width // SIDE)
        errors.append(delta.sum(axis=(1, 3)).ravel())
        coverage_xor = np.logical_xor(lower > 0, upper > 0).reshape(
            SIDE, scene.height // SIDE, SIDE, scene.width // SIDE)
        silhouette_errors.append(coverage_xor.sum(axis=(1, 3)).astype(np.float64).ravel())
        if (image_stride is not None and
                (index % image_stride == 0 or index == len(poses) - 1)):
            image_pairs.append((index, lower, upper))
    return (np.stack(errors), np.stack(silhouette_errors)), image_pairs


def image_metrics(poses, errors, image_pairs, table, keep, chosen):
    """Report exact per-frame PSNR and sampled SSIM/silhouette IoU."""
    policies = tuple(dict.fromkeys(("area-hysteresis", f"{chosen}-hysteresis")))
    report = {policy: {"frameMetrics": [], "sampledStructuralMetrics": []}
              for policy in policies}
    for policy in policies:
        previous = old_benefit = None
        selections = []
        for index, pose in enumerate(poses):
            selected, benefit = choose(policy, pose[1], pose[2], table, keep,
                                       previous, old_benefit)
            sse = float(errors[index][~selected].sum())
            mse = sse / image_pairs[0][2].size
            selections.append(selected)
            report[policy]["frameMetrics"].append({
                "frame": index,
                "psnrDb": None if mse == 0 else float(-10 * math.log10(mse)),
                "mse": mse,
            })
            previous, old_benefit = selected, benefit
        sampled = set(np.linspace(0, len(poses) - 1, 4, dtype=int).tolist())
        for index, lower, reference in image_pairs:
            if index not in sampled:
                continue
            height, width = reference.shape
            tile_h, tile_w = height // SIDE, width // SIDE
            low_tiles = lower.reshape(SIDE, tile_h, SIDE, tile_w)
            high_tiles = reference.reshape(SIDE, tile_h, SIDE, tile_w)
            mask = selections[index].reshape(SIDE, SIDE)[:, None, :, None]
            candidate = np.where(mask, high_tiles, low_tiles).reshape(height, width)
            union = np.logical_or(reference > 0, candidate > 0).sum()
            intersection = np.logical_and(reference > 0, candidate > 0).sum()
            report[policy]["sampledStructuralMetrics"].append({
                "frame": index,
                "ssim": float(structural_similarity(
                    reference, candidate, data_range=255, gaussian_weights=True,
                    sigma=1.5, use_sample_covariance=False)),
                "silhouetteIou": 1.0 if union == 0 else float(intersection / union),
            })
    report["calibrated-hysteresis"] = report[f"{chosen}-hysteresis"]
    return report


def write_lossless_rgb_video(path, frames, fps):
    import cv2

    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"FFV1"), fps,
                             (width, height), True)
    if not writer.isOpened():
        raise RuntimeError("OpenCV FFmpeg cannot encode FFV1 video")
    try:
        for frame in frames:
            rgb = np.repeat(frame[..., None], 3, axis=2) if frame.ndim == 2 else frame
            writer.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    finally:
        writer.release()

    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        raise RuntimeError(f"Could not reopen captured sequence: {path}")
    try:
        if (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) != width or
                int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) != height or
                int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != len(frames) or
                not math.isclose(capture.get(cv2.CAP_PROP_FPS), fps, rel_tol=0, abs_tol=1e-6)):
            raise RuntimeError(f"Captured sequence metadata mismatch: {path}")
        for index, expected in enumerate(frames):
            ok, bgr = capture.read()
            if not ok:
                raise RuntimeError(f"Could not decode frame {index} from {path}")
            decoded = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            expected_rgb = (np.repeat(expected[..., None], 3, axis=2)
                            if expected.ndim == 2 else expected)
            if not np.array_equal(decoded, expected_rgb):
                raise RuntimeError(f"Lossless sequence round-trip mismatch at frame {index}: {path}")
    finally:
        capture.release()
    data = path.read_bytes()
    return {"path": path.as_posix(), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "width": width, "height": height,
            "frameCount": len(frames), "fps": fps, "codec": "FFV1"}


def temporal_difference_metrics(poses, image_pairs, table, keep, chosen,
                                sequence_dir=None, sequence_fps=30):
    """Measure temporal image-derivative error; this is not a perceptual VQA score."""
    by_frame = {index: (low, high) for index, low, high in image_pairs}
    policies = tuple(dict.fromkeys(("area-hysteresis", f"{chosen}-hysteresis")))
    report = {}
    for policy in policies:
        previous = old_benefit = None
        candidates, references, selections = [], [], []
        for index, pose in enumerate(poses):
            selected, benefit = choose(policy, pose[1], pose[2], table, keep,
                                       previous, old_benefit)
            low, high = by_frame[index]
            height, width = high.shape
            tile_h, tile_w = height // SIDE, width // SIDE
            low_tiles = low.reshape(SIDE, tile_h, SIDE, tile_w)
            high_tiles = high.reshape(SIDE, tile_h, SIDE, tile_w)
            mask = selected.reshape(SIDE, SIDE)[:, None, :, None]
            candidate = np.where(mask, high_tiles, low_tiles).reshape(height, width)
            candidates.append(candidate)
            references.append(high)
            selections.append(selected)
            previous, old_benefit = selected, benefit

        candidate_video = np.stack(candidates).astype(np.float32)
        reference_video = np.stack(references).astype(np.float32)
        sequence_files = None
        if sequence_dir is not None:
            sequence_dir.mkdir(parents=True, exist_ok=True)
            reference_path = sequence_dir / "reference.mkv"
            candidate_path = sequence_dir / f"{policy}.mkv"
            if not reference_path.exists():
                reference_file = write_lossless_rgb_video(
                    reference_path, references, sequence_fps)
            else:
                reference_file = {"path": reference_path.as_posix(),
                                  "sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                                  "bytes": reference_path.stat().st_size,
                                  "width": references[0].shape[1],
                                  "height": references[0].shape[0],
                                  "frameCount": len(references), "fps": sequence_fps,
                                  "codec": "FFV1"}
            candidate_file = write_lossless_rgb_video(
                candidate_path, candidates, sequence_fps)
            sequence_files = {"candidate": candidate_file, "reference": reference_file}
        temporal_residual = (candidate_video[1:] - candidate_video[:-1]) - (
            reference_video[1:] - reference_video[:-1])
        active = np.logical_or(candidate_video > 0, reference_video > 0)
        active = np.logical_or(active[1:], active[:-1])
        absolute = np.abs(temporal_residual)
        squared = np.square(temporal_residual, dtype=np.float64)
        support_mae = []
        support_rmse = []
        for frame in range(len(temporal_residual)):
            mask = active[frame]
            if np.any(mask):
                values = absolute[frame][mask]
                support_mae.append(float(values.mean() / 255.0))
                support_rmse.append(float(np.sqrt(squared[frame][mask].mean()) / 255.0))
            else:
                support_mae.append(0.0)
                support_rmse.append(0.0)
        switch_counts = [int(np.count_nonzero(selections[i] ^ selections[i - 1]))
                         for i in range(1, len(selections))]
        switched = [i for i, count in enumerate(switch_counts) if count > 0]
        stable = [i for i, count in enumerate(switch_counts) if count == 0]
        report[policy] = {
            "definition": "Adjacent-frame candidate-minus-reference image difference; normalized by 255",
            "framePairs": len(temporal_residual),
            "fullFrameMae": float(absolute.mean() / 255.0),
            "fullFrameRmse": float(np.sqrt(squared.mean()) / 255.0),
            "foregroundSupportMae": float(np.mean(support_mae)),
            "foregroundSupportRmse": float(np.mean(support_rmse)),
            "foregroundPairMaeP95": float(np.quantile(support_mae, 0.95)),
            "lodSwitchTransitions": len(switched),
            "meanForegroundPairMaeAtSwitch": (float(np.mean([support_mae[i] for i in switched]))
                                                if switched else 0.0),
            "meanForegroundPairMaeWithoutSwitch": (float(np.mean([support_mae[i] for i in stable]))
                                                     if stable else 0.0),
        }
        if sequence_files is not None:
            report[policy]["sequenceFiles"] = sequence_files
    report["calibrated-hysteresis"] = report[f"{chosen}-hysteresis"]
    return report


def compare_policies(scene, meshes, poses, errors, table, keep, chosen):
    report = {}
    frame = len(poses) // 2
    low = scene.capture(meshes, poses[frame], np.zeros(COUNT, dtype=bool))
    high = scene.capture(meshes, poses[frame], np.ones(COUNT, dtype=bool))
    options = [(policy, None) for policy in (*POLICIES, "calibrated-hysteresis", "frame-oracle")]
    options.extend((policy, margin) for policy in (
        "area-hysteresis", "area-switch-cost", "direction-hysteresis",
                   "direction-switch-cost", "scale-direction-switch-cost") for margin in MARGINS)
    for policy, margin in options:
        prev = old_benefit = None
        rows = []
        for index, (pose, error) in enumerate(zip(poses, errors, strict=True)):
            if policy == "frame-oracle":
                selected = np.zeros(COUNT, dtype=bool)
                selected[np.argsort(-error, kind="stable")[:keep]] = True
            else:
                ranker = f"{chosen}-hysteresis" if policy == "calibrated-hysteresis" else policy
                selected, old_benefit = choose(ranker, pose[1], pose[2], table,
                                               keep, prev, old_benefit, margin)
            changes = selected ^ prev if prev is not None else np.zeros(COUNT, dtype=bool)
            switch_sse = float(error[changes].sum())
            if index == frame and margin is None:
                realized = scene.capture(meshes, pose, selected)
                tile_mask = np.repeat(np.repeat(selected.reshape(SIDE, SIDE),
                                                scene.height // SIDE, axis=0),
                                      scene.width // SIDE, axis=1)
                expected = np.where(tile_mask, high, low)
                if not np.array_equal(expected, realized):
                    raise RuntimeError("Mixed GPU draw differs from isolated-cell reference")
                carried = scene.capture(meshes, pose, prev)
                change = (realized.astype(np.float32) - carried) / 255
                observed = np.square(change, dtype=np.float64).sum()
                if not math.isclose(observed, switch_sse, rel_tol=1e-12, abs_tol=1e-12):
                    raise RuntimeError("Mixed GPU draw disagrees with same-pose switch SSE")
            rows.append({"sse": float(error[~selected].sum()),
                         "switchCount": int(changes.sum()), "switchSse": switch_sse})
            prev = selected
        label = policy if margin is None else f"{policy}@{margin:.2f}"
        report[label] = rows
    return report


def benchmark_policies(scene, meshes, path, table, keep, chosen, repetitions, path_index):
    pairs = (("area-hysteresis", "area-hysteresis"),
             ("direction-switch-cost", "direction-switch-cost"),
             ("scale-direction-switch-cost", "scale-direction-switch-cost"),
             ("calibrated-hysteresis", f"{chosen}-hysteresis"))
    output = {label: {"gpuMs": [], "cpuMs": [], "selectorMs": []} for label, _ in pairs}
    for turn in range(repetitions):
        first = (turn + path_index) % len(pairs)
        for label, policy in pairs[first:] + pairs[:first]:
            for key, measurements in scene.measure(meshes, path, table, keep, policy).items():
                output[label][key].extend(measurements)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meshes", type=Path)
    parser.add_argument("--motion-reference", type=Path, required=True)
    parser.add_argument("--asset", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", choices=("640x360", "1280x720", "1920x1080"), default="1280x720")
    parser.add_argument("--frames", type=int, choices=(24, 48), default=48)
    parser.add_argument("--keep", type=int, choices=(2, 4, 8), default=4)
    parser.add_argument("--test-pair", choices=("initial", "alternate"), default="initial")
    parser.add_argument("--timing-repeats", type=int, choices=(1, 3), default=3)
    parser.add_argument("--sequence-dir", type=Path,
                        help="Write validated lossless CGVQM-ready videos under this directory")
    parser.add_argument("--sequence-fps", type=int, default=30)
    parser.add_argument("--profile-scope", choices=("per-asset", "leave-one-asset-out"),
                        default="per-asset")
    parser.add_argument("--profile-objective",
                        choices=("color-sse", "silhouette-xor", "balanced-color-silhouette"),
                        default="color-sse")
    args = parser.parse_args()
    if args.sequence_fps <= 0:
        parser.error("--sequence-fps must be positive")
    width, height = (int(size) for size in args.size.split("x"))
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    scene = Scene(adapter.request_device_sync(required_features=["timestamp-query"]), width, height)
    manifest = json.loads(args.motion_reference.read_text(encoding="utf-8"))
    print(dict(adapter.info), flush=True)
    training = trajectory(width, height, 24, 0)
    path_indices = (1, 2) if args.test_pair == "initial" else (3, 4)
    testing = [trajectory(width, height, args.frames, path) for path in path_indices]
    asset_names = list(dict.fromkeys(args.asset))
    if args.profile_scope == "leave-one-asset-out" and len(asset_names) < 3:
        parser.error("Leave-one-asset-out profiling needs at least three distinct assets")
    training_errors = {}
    for name in args.asset:
        exports = manifest["assets"][name]["exports"]
        meshes = []
        for kind in ("parts", "source"):
            vertices, indices = load_export(args.meshes / name / f"{kind}.ply", exports[kind])
            meshes.append((scene.device.create_buffer_with_data(data=vertices, usage=wgpu.BufferUsage.VERTEX),
                           scene.device.create_buffer_with_data(data=indices, usage=wgpu.BufferUsage.INDEX),
                           len(indices)))
        (train_color_error, train_silhouette_error), _ = error_table(scene, meshes, training)
        training_errors[name] = profile_objective_errors(
            train_color_error, train_silhouette_error, args.profile_objective)
        for v, i, _ in meshes:
            v.destroy()
            i.destroy()

    if args.profile_scope == "leave-one-asset-out":
        selected_rankers, validation_scores, tables = {}, {}, {}
        for name in asset_names:
            other_assets = {key: value for key, value in training_errors.items() if key != name}
            selected_rankers[name], validation_scores[name] = cross_validated_ranker_by_asset(
                training, other_assets, args.keep)
            tables[name] = shared_profile(training, other_assets, name)
    else:
        selected_rankers, validation_scores, tables = {}, {}, {}
        for name, train_error in training_errors.items():
            tables[name] = calibrate(training, train_error)
            selected_rankers[name], validation_scores[name] = cross_validated_ranker(
                training, train_error, args.keep)

    results = {}
    for name in asset_names:
        exports = manifest["assets"][name]["exports"]
        meshes = []
        for kind in ("parts", "source"):
            vertices, indices = load_export(args.meshes / name / f"{kind}.ply", exports[kind])
            meshes.append((scene.device.create_buffer_with_data(data=vertices, usage=wgpu.BufferUsage.VERTEX),
                           scene.device.create_buffer_with_data(data=indices, usage=wgpu.BufferUsage.INDEX),
                           len(indices)))
        table = tables[name]
        chosen = selected_rankers[name]
        calibration_scores = validation_scores[name]
        quality, image_quality, temporal_quality, runtime = [], [], [], []
        for path_index, path in enumerate(testing):
            (color_errors, _), image_pairs = error_table(scene, meshes, path, image_stride=1)
            quality.append(compare_policies(scene, meshes, path, color_errors, table, args.keep, chosen))
            image_quality.append(image_metrics(path, color_errors, image_pairs,
                                               table, args.keep, chosen))
            sequence_dir = (args.sequence_dir / name / f"path-{path_indices[path_index]}"
                            if args.sequence_dir is not None else None)
            temporal_quality.append(temporal_difference_metrics(
                path, image_pairs, table, args.keep, chosen, sequence_dir,
                args.sequence_fps))
            runtime.append(benchmark_policies(scene, meshes, path, table, args.keep, chosen,
                                               args.timing_repeats, path_index))
        faces = args.keep * exports["source"]["faces"] + (COUNT - args.keep) * exports["parts"]["faces"]
        results[name] = {"faceCount": faces, "directionalDensity": table[0].tolist(),
                         "sizeDirectionalDensity": table[1].tolist(),
                         "apparentSizeBins": table[2].tolist(),
                         "calibratedRanker": chosen, "calibrationSse": calibration_scores,
                         "quality": quality, "imageQuality": image_quality,
                         "temporalDifferenceQuality": temporal_quality, "runtime": runtime}
        for v, i, _ in meshes:
            v.destroy()
            i.destroy()
        print(name, faces, "triangles per frame", flush=True)
    report = {"adapter": dict(adapter.info),
              "wgpuVersion": importlib.metadata.version("wgpu"),
              "profileScope": args.profile_scope,
              "profileObjective": args.profile_objective,
              "profileNormalization": ("per-asset mean training objective loss"
                                       if args.profile_scope == "leave-one-asset-out" else None),
              "profileTrainingAssetsPerFold": len(asset_names) - 1 if args.profile_scope == "leave-one-asset-out" else 1,
              "inputHashes": {
                  "motionReferenceSha256": hashlib.sha256(args.motion_reference.read_bytes()).hexdigest(),
                  "meshes": {name: {kind: manifest["assets"][name]["exports"][kind]["sha256"]
                                    for kind in ("source", "parts")}
                             for name in asset_names},
              },
              "size": [width, height], "framesPerPath": args.frames,
              "sequenceFps": args.sequence_fps if args.sequence_dir is not None else None,
              "fineInstances": args.keep, "timestampPeriodNs": scene.period,
              "timingRepeats": args.timing_repeats, "warmupFrames": 8,
              "testPaths": path_indices, "assets": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

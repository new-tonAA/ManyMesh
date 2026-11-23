"""Measure dynamic per-instance LOD and its complete CPU/GPU frame-path cost."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import wgpu
from skimage.metrics import structural_similarity

from bench_bevy_smaa import PINNED
from bench_component_gpu import linear_gray_to_srgb, projection_matrix, select_adapter
from bench_dynamic_lod import write_lossless_rgb_video
from bench_mixed_scene_layout import COMMIT, pack_geometry, read_geometry
from bench_mixed_scenes import SceneRaster, SceneReference, gpu_mesh, sha
from bench_scene_instance_lod import bound_areas, exact_subset, greedy_subset, set_up_instances
from bench_scene_lod_allocation import make_plans
from gray_flip import gray_flip


def percentile(values, p):
    return float(np.percentile(np.asarray(values, dtype=np.float64), p))


def make_path(eyes, frames):
    """Loop smoothly through the three frozen benchmark eyes."""
    keys = np.asarray(eyes, dtype=np.float64)
    t = np.arange(frames, dtype=np.float64) * len(keys) / frames
    segment = np.floor(t).astype(int)
    u = t - segment
    smooth = u * u * (3.0 - 2.0 * u)
    return (1.0 - smooth[:, None]) * keys[segment % len(keys)] + smooth[:, None] * keys[(segment + 1) % len(keys)]


def exact_group_subset(costs, values, cap):
    # The number of clean asset groups is at most eight, so enumeration is exact and cheap.
    best_mask, best_value, best_cost = 0, -1, 0
    for mask in range(1 << len(costs)):
        cost = sum(int(costs[i]) for i in range(len(costs)) if mask & (1 << i))
        if cost > cap:
            continue
        value = sum(int(values[i]) for i in range(len(values)) if mask & (1 << i))
        if value > best_value or (value == best_value and cost < best_cost):
            best_mask, best_value, best_cost = mask, value, cost
    return np.asarray([bool(best_mask & (1 << i)) for i in range(len(costs))])


def image_metrics(reference, candidate):
    ref = reference.astype(np.float64) / 255.0
    img = candidate.astype(np.float64) / 255.0
    mse = float(np.mean(np.square(ref - img), dtype=np.float64))
    return {
        "flip": gray_flip(reference, candidate),
        "psnr_db": None if mse == 0.0 else -10.0 * np.log10(mse),
        "ssim": float(structural_similarity(reference, candidate, data_range=255,
                                              gaussian_weights=True, sigma=1.5,
                                              use_sample_covariance=False)),
        "silhouette_xor_fraction": float(np.mean((reference > 0) != (candidate > 0))),
    }


def capture_msaa(raster, draws):
    encoder = raster.device.create_command_encoder()
    raster.encode(encoder, draws, "msaa4")
    raster.queue.submit([encoder.finish()])
    raw = raster.queue.read_texture(
        {"texture": raster.output},
        {"bytes_per_row": raster.width * 4, "rows_per_image": raster.height},
        (raster.width, raster.height, 1))
    return np.frombuffer(raw, dtype=np.uint8).reshape(raster.height, raster.width, 4)[..., 0].copy()


def temporal_diagnostic(images, references, selected):
    errors_at_switch, errors_without_switch = [], []
    frame_pair_mae = []
    for i in range(1, len(images)):
        candidate_delta = images[i].astype(np.int16) - images[i - 1].astype(np.int16)
        reference_delta = references[i].astype(np.int16) - references[i - 1].astype(np.int16)
        support = ((images[i] > 0) | (images[i - 1] > 0) |
                   (references[i] > 0) | (references[i - 1] > 0))
        values = np.abs(candidate_delta - reference_delta)[support]
        mae = float(values.mean() / 255.0) if len(values) else 0.0
        frame_pair_mae.append(mae)
        if selected[i] != selected[i - 1]:
            errors_at_switch.append(mae)
        else:
            errors_without_switch.append(mae)
    return {
        "definition": "Foreground-supported adjacent-frame candidate-minus-reference difference; no optical-flow compensation",
        "framePairs": len(frame_pair_mae),
        "meanForegroundPairMae": float(np.mean(frame_pair_mae)) if frame_pair_mae else 0.0,
        "p95ForegroundPairMae": percentile(frame_pair_mae, 95) if frame_pair_mae else 0.0,
        "lodSwitchTransitions": int(sum(selected[i] != selected[i - 1]
                                         for i in range(1, len(selected)))),
        "instanceSwitches": int(sum(len(selected[i] ^ selected[i - 1])
                                     for i in range(1, len(selected)))),
        "switchedPairs": len(errors_at_switch),
        "meanMaeAtSwitch": float(np.mean(errors_at_switch)) if errors_at_switch else None,
        "meanMaeWithoutSwitch": float(np.mean(errors_without_switch)) if errors_without_switch else None,
    }


class DynamicBuckets:
    """Persistent per-asset vertex buffers updated with the selected instance lists."""

    def __init__(self, device, scene, groups, meshes, instance):
        self.device = device
        self.scene = scene
        self.groups = tuple(groups)
        self.group_set = set(groups)
        self.meshes = meshes
        self.instance = instance
        self.transforms = {asset: np.asarray(values, dtype=np.float32)
                           for asset, values in scene["instance_transforms"].items()}
        self.buffers = {}
        self.static_source = {}
        for asset, transforms in self.transforms.items():
            self.static_source[asset] = device.create_buffer_with_data(
                data=np.ascontiguousarray(transforms, dtype=np.float32),
                usage=wgpu.BufferUsage.VERTEX)
            if asset in self.group_set:
                for kind in ("cluster1", "cluster2"):
                    self.buffers[asset, kind] = device.create_buffer(
                        size=max(24, transforms.nbytes),
                        usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self.id_to_asset = {}
        self.id_to_local = {}
        for asset, identifiers in instance["ids"].items():
            for local, identifier in enumerate(identifiers):
                self.id_to_asset[int(identifier)] = asset
                self.id_to_local[int(identifier)] = local
        self.group_costs = np.asarray([
            instance["costs"][np.isin(instance["eligible"], instance["ids"][asset])].sum()
            for asset in groups
        ], dtype=np.int64)
        self.id_positions = {int(identifier): i for i, identifier in enumerate(instance["eligible"])}
        self.group_slot = {asset: i for i, asset in enumerate(groups)}

    def select(self, eye, width, height, base_faces, cap_extra, policy):
        areas = bound_areas(self.instance["world_corners"], eye, width, height)
        costs = self.instance["costs"]
        if policy == "instance-area":
            flags = greedy_subset(costs, areas, cap_extra)
            promoted = set(int(v) for v in self.instance["eligible"][flags])
            faces = int(base_faces + costs[flags].sum())
            return promoted, faces, areas, base_faces + cap_extra
        if policy in ("group-area", "instance-matched"):
            values = []
            for asset in self.groups:
                ids = self.instance["ids"][asset]
                slots = [self.id_positions[int(identifier)] for identifier in ids]
                values.append(int(areas[slots].sum()))
            flags = exact_group_subset(self.group_costs, np.asarray(values), cap_extra)
            promoted = set(int(v) for i, asset in enumerate(self.groups) if flags[i]
                           for v in self.instance["ids"][asset])
            group_faces = int(base_faces + self.group_costs[flags].sum())
            if policy == "group-area":
                return promoted, group_faces, areas, group_faces
            # Diagnostic control: spend no more than the group's actual per-frame
            # face count, using the same projected-area objective at instance granularity.
            instance_flags = exact_subset(costs, areas, group_faces - base_faces)
            promoted = set(int(v) for v in self.instance["eligible"][instance_flags])
            faces = int(base_faces + costs[instance_flags].sum())
            if faces > group_faces:
                raise RuntimeError("Face-matched instance oracle exceeded the group budget")
            return promoted, faces, areas, group_faces
        raise ValueError(f"Unknown dynamic policy: {policy}")

    def make_draws(self, policy, promoted):
        draws = []
        for asset in self.scene["asset_order"]:
            transforms = self.transforms[asset]
            if asset not in self.group_set:
                positions, indices, count = self.meshes[asset, "source"]
                draws.append((positions, indices, count, self.static_source[asset], len(transforms)))
                continue
            if policy == "source":
                positions, indices, count = self.meshes[asset, "source"]
                draws.append((positions, indices, count, self.static_source[asset], len(transforms)))
                continue
            flags = np.fromiter((int(identifier) in promoted for identifier in self.instance["ids"][asset]),
                                dtype=bool, count=len(transforms))
            for kind, use in (("cluster2", ~flags), ("cluster1", flags)):
                if not np.any(use):
                    continue
                payload = np.ascontiguousarray(transforms[use], dtype=np.float32)
                buffer = self.buffers[asset, kind]
                self.device.queue.write_buffer(buffer, 0, payload)
                positions, indices, count = self.meshes[asset, kind]
                draws.append((positions, indices, count, buffer, int(use.sum())))
        return draws

    def destroy(self):
        for buffer in [*self.buffers.values(), *self.static_source.values()]:
            buffer.destroy()


def run_dynamic_path(raster, buckets, eyes, frames, groups, base_faces, face_cap,
                     policy, repetitions, warmups=8):
    path = make_path(eyes, frames)
    cap_extra = int(face_cap - base_faces)
    for i in range(warmups):
        eye = path[i % frames]
        if policy == "source":
            promoted = set()
        else:
            promoted, _, _, _ = buckets.select(eye, raster.width, raster.height,
                                                base_faces, cap_extra, policy)
        draws = buckets.make_draws(policy, promoted)
        raster.camera_at(eye)
        encoder = raster.device.create_command_encoder()
        raster.encode(encoder, draws, "msaa4")
        raster.queue.submit([encoder.finish()])
    raster.queue.read_texture(
        {"texture": raster.output},
        {"bytes_per_row": raster.width * 4, "rows_per_image": raster.height},
        (raster.width, raster.height, 1))

    reps = []
    for repetition in range(repetitions):
        query = raster.device.create_query_set(type="timestamp", count=2 * frames)
        resolved = raster.device.create_buffer(
            size=16 * frames,
            usage=wgpu.BufferUsage.QUERY_RESOLVE | wgpu.BufferUsage.COPY_SRC)
        selector_ms, update_submit_ms = [], []
        faces, comparison_faces, draws_per_frame, selections = [], [], [], []
        started = time.perf_counter()
        for frame, eye in enumerate(path):
            choice_start = time.perf_counter()
            if policy == "source":
                promoted = set()
                frame_faces = None
            else:
                promoted, frame_faces, _, frame_budget = buckets.select(
                    eye, raster.width, raster.height, base_faces, cap_extra, policy)
                comparison_faces.append(frame_budget)
            selected_at = time.perf_counter()
            draws = buckets.make_draws(policy, promoted)
            raster.camera_at(eye)
            encoder = raster.device.create_command_encoder()
            raster.encode(encoder, draws, "msaa4", query, frame * 2)
            raster.queue.submit([encoder.finish()])
            submitted_at = time.perf_counter()
            selector_ms.append((selected_at - choice_start) * 1000.0)
            update_submit_ms.append((submitted_at - selected_at) * 1000.0)
            faces.append(frame_faces)
            draws_per_frame.append(len(draws))
            selections.append(sorted(promoted))
        encoder = raster.device.create_command_encoder()
        encoder.resolve_query_set(query, 0, 2 * frames, resolved, 0)
        raster.queue.submit([encoder.finish()])
        ticks = np.frombuffer(raster.queue.read_buffer(resolved), dtype="<u8").reshape(frames, 2)
        finished = time.perf_counter()
        query.destroy()
        resolved.destroy()
        if np.any(ticks[:, 1] <= ticks[:, 0]):
            raise RuntimeError("Invalid moving-scene timestamp ordering")
        gpu_ms = (ticks[:, 1] - ticks[:, 0]) * (raster.timestamp_ns / 1e6)
        if policy != "source" and max(faces) > face_cap:
            raise RuntimeError(f"{policy} exceeded the frozen face cap")
        if (policy == "instance-matched" and
                any(face > budget for face, budget in zip(faces, comparison_faces, strict=True))):
            raise RuntimeError("Matched instance allocation exceeded its per-frame comparison budget")
        reps.append({
            "gpu_ms": gpu_ms.tolist(),
            "selector_cpu_ms": selector_ms,
            "bucket_camera_encode_submit_cpu_ms": update_submit_ms,
            "synchronized_path_wall_ms": (finished - started) * 1000.0,
            "mean_faces": None if policy == "source" else float(np.mean(faces)),
            "max_faces": None if policy == "source" else int(max(faces)),
            "comparison_face_budgets": comparison_faces,
            "mean_draws": float(np.mean(draws_per_frame)),
            "faces_by_frame": faces,
            "draws_by_frame": draws_per_frame,
            "selections": selections,
        })
    return path, reps


def capture_sequence(raster, high, buckets, static_draws, eyes, frames, groups,
                     base_faces, face_cap, policy, sequence_dir, scene_name,
                     reference_frames=None, reference_video_info=None):
    path = make_path(eyes, frames)
    refs, candidates, selected_by_frame = [], [], []
    cap_extra = int(face_cap - base_faces)
    for frame_index, eye in enumerate(path):
        if policy == "source":
            promoted = set()
        else:
            promoted, _, _, _ = buckets.select(eye, raster.width, raster.height,
                                                base_faces, cap_extra, policy)
        draws = static_draws if policy == "source" else buckets.make_draws(policy, promoted)
        raster.camera_at(eye)
        low = capture_msaa(raster, draws)
        if reference_frames is None:
            high.camera_at(eye)
            high_raw = capture_msaa(high, static_draws)
            high_srgb = linear_gray_to_srgb(
                high_raw.reshape(raster.height, 2, raster.width, 2).mean(axis=(1, 3)))
        else:
            high_srgb = reference_frames[frame_index]
        low_srgb = linear_gray_to_srgb(low)
        refs.append(high_srgb)
        candidates.append(low_srgb)
        selected_by_frame.append(set(promoted))
    frame_rows = [image_metrics(ref, img) for ref, img in zip(refs, candidates, strict=True)]
    (sequence_dir / scene_name).mkdir(parents=True, exist_ok=True)
    candidate_file = write_lossless_rgb_video(
        sequence_dir / scene_name / f"{policy}.mkv", candidates, 30)
    if reference_video_info is None:
        reference_video_info = write_lossless_rgb_video(
            sequence_dir / scene_name / "reference.mkv", refs, 30)
    reference_frames_out = refs if reference_frames is None else reference_frames
    reference_rgb_sha = sha(b"".join(frame.tobytes() for frame in refs))
    temporal = temporal_diagnostic(candidates, refs, selected_by_frame)
    return {
        "reference_sequence": reference_video_info,
        "reference_rgb_sha256": reference_rgb_sha,
        "_reference_frames": reference_frames_out,
        "candidate_sequence": candidate_file,
        "per_frame_metrics": frame_rows,
        "mean_metrics": {key: float(np.mean([row[key] for row in frame_rows if row[key] is not None]))
                         for key in ("flip", "psnr_db", "ssim", "silhouette_xor_fraction")},
        "p95_flip": percentile([row["flip"] for row in frame_rows], 95),
        "temporal_diagnostic": temporal,
        "camera_eyes": path.tolist(),
        "decoded_video_roundtrip": "validated by write_lossless_rgb_video",
    }


def summarize_repetitions(repetitions):
    gpu = np.concatenate([np.asarray(row["gpu_ms"]) for row in repetitions])
    selector = np.concatenate([np.asarray(row["selector_cpu_ms"]) for row in repetitions])
    update = np.concatenate([np.asarray(row["bucket_camera_encode_submit_cpu_ms"])
                             for row in repetitions])
    walls = np.asarray([row["synchronized_path_wall_ms"] / len(row["gpu_ms"])
                        for row in repetitions])
    valid_faces = [row["mean_faces"] for row in repetitions if row["mean_faces"] is not None]
    return {
        "gpu_ms_p50": percentile(gpu, 50),
        "gpu_ms_p95": percentile(gpu, 95),
        "selector_cpu_ms_p50": percentile(selector, 50),
        "selector_cpu_ms_p95": percentile(selector, 95),
        "bucket_camera_encode_submit_cpu_ms_p50": percentile(update, 50),
        "bucket_camera_encode_submit_cpu_ms_p95": percentile(update, 95),
        "synchronized_path_wall_ms_per_frame_median": float(np.median(walls)),
        "mean_faces_across_repetitions": float(np.mean(valid_faces)) if valid_faces else None,
        "comparison_face_budget_mean": float(np.mean([
            np.mean(row["comparison_face_budgets"]) for row in repetitions
            if row["comparison_face_budgets"]
        ])) if any(row["comparison_face_budgets"] for row in repetitions) else None,
        "draws_per_frame_median": float(np.median([row["mean_draws"] for row in repetitions])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--meshes", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--shader-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sequence-dir", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=48)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--scene", action="append")
    args = parser.parse_args()
    if args.frames < 12 or args.repetitions < 1:
        parser.error("Use at least 12 frames and one timing repetition")

    baseline_bytes = args.baseline.read_bytes()
    allocation_bytes = args.allocation.read_bytes()
    baseline, allocation = json.loads(baseline_bytes), json.loads(allocation_bytes)
    if allocation["baseline_sha256"] != sha(baseline_bytes):
        parser.error("The allocation receipt does not belong to this mixed-scene baseline")
    selected_scenes = args.scene or list(baseline["scenes"])
    if any(name not in baseline["scenes"] for name in selected_scenes):
        parser.error("Unknown scene selected")
    repo = ["git", "-C", str(args.upstream)]
    if (json.loads((args.stock / "cluster-cuts.json").read_text(encoding="utf-8"))
            .get("meshoptimizer_commit") not in (None, COMMIT)):
        parser.error("Unexpected meshoptimizer cluster-cut revision")
    if __import__("subprocess").check_output(repo + ["rev-parse", "HEAD"], text=True).strip() != COMMIT:
        parser.error("Expected the pinned stock meshoptimizer checkout")
    encoder = args.upstream / "js/meshopt_encoder.js"
    if sha(encoder.read_bytes()) != allocation["encoder_sha256"]:
        parser.error("Meshoptimizer encoder hash differs from the frozen receipt")
    for name, digest in PINNED.items():
        if sha((args.shader_root / name).read_bytes()) != digest:
            parser.error(f"Bevy shader asset differs: {name}")

    originals = read_geometry(baseline, args.meshes, args.stock)
    packed, _ = pack_geometry(originals, encoder)
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    if dict(adapter.info) != baseline["adapter"] or wgpu.__version__ != baseline["wgpu"]:
        raise RuntimeError("GPU adapter or wgpu version changed")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    width, height = baseline["size"]
    raster = SceneRaster(device, width, height, args.shader_root)
    high = SceneReference(device, width * 2, height * 2, 1, False)
    meshes = {(asset, kind): gpu_mesh(device, vertices, indices)
              for (asset, kind, layout), (vertices, indices) in packed.items()
              if layout == "cache-fetch"}
    supplied = {asset: gpu_mesh(device, *originals[asset, "source"])
                for asset in baseline["assets"]}
    report = {
        "baseline_sha256": sha(baseline_bytes),
        "allocation_sha256": sha(allocation_bytes),
        "script_sha256": sha(Path(__file__).read_bytes()),
        "meshoptimizer_commit": COMMIT,
        "adapter": dict(adapter.info),
        "wgpu_version": wgpu.__version__,
        "resolution": [width, height],
        "reference_resolution": [width * 2, height * 2],
        "frames": args.frames,
        "fps": 30,
        "repetitions": args.repetitions,
        "camera_path": "piecewise-smooth loop through the three frozen per-scene benchmark eyes",
        "quality_reference": "full source, 4x MSAA at 2x resolution, linear-light 2x box downsample",
        "policies": ["source", "group-area", "instance-area", "instance-matched"],
        "scenes": {},
    }
    args.sequence_dir.mkdir(parents=True, exist_ok=True)
    for name in selected_scenes:
        frozen = baseline["scenes"][name]
        group_order, masks, triangle_counts, static_modes, reference_draws, instance_buffers = make_plans(
            device, frozen, baseline["assets"], meshes, supplied)
        expected = allocation["scenes"][name]
        if group_order != expected["groups"] or triangle_counts != expected["mask_triangle_counts"]:
            raise RuntimeError(f"Frozen incidence group or face-count mismatch in {name}")
        instance = set_up_instances(device, frozen, group_order, meshes, originals)
        bucket = DynamicBuckets(device, frozen, group_order, meshes, instance)
        low_faces, high_faces = triangle_counts[0], triangle_counts[-1]
        face_cap = low_faces + (high_faces - low_faces) // 2
        eyes = [view["eye"] for view in frozen["views"]]
        result = {"groups": group_order, "low_faces": low_faces,
                  "high_faces": high_faces, "face_cap": face_cap,
                  "views": {}}
        reference_video_sha = None
        reference_frames = None
        reference_video_info = None
        for policy in ("source", "group-area", "instance-area", "instance-matched"):
            path, runs = run_dynamic_path(
                raster, bucket, eyes, args.frames, group_order, low_faces,
                face_cap, policy, args.repetitions)
            summary = summarize_repetitions(runs)
            seq = capture_sequence(
                raster, high, bucket, reference_draws, eyes, args.frames,
                group_order, low_faces, face_cap, policy,
                args.sequence_dir, name, reference_frames,
                reference_video_info)
            seq_reference_frames = seq.pop("_reference_frames")
            if reference_frames is None:
                reference_frames = seq_reference_frames
                reference_video_info = seq["reference_sequence"]
            current_reference_sha = seq["reference_sequence"]["sha256"]
            if reference_video_sha is None:
                reference_video_sha = current_reference_sha
            elif current_reference_sha != reference_video_sha:
                raise RuntimeError(f"Full-source reference sequence changed between policies in {name}")
            summary.update({"timing_repetitions": runs,
                            "quality_sequence": seq,
                            "camera_path_matches_timing": np.array_equal(
                                np.asarray(path), np.asarray(seq["camera_eyes"]))})
            result["views"][policy] = summary
            print(name, policy, "GPU p50", round(summary["gpu_ms_p50"], 4),
                  "CPU select p50", round(summary["selector_cpu_ms_p50"], 4),
                  "wall/frame", round(summary["synchronized_path_wall_ms_per_frame_median"], 4),
                  flush=True)
        report["scenes"][name] = result
        bucket.destroy()
        for buffer in [*instance["id_buffers"], *instance_buffers.values()]:
            buffer.destroy()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()

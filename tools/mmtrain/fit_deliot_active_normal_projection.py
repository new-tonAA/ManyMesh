"""Fit fixed-topology meshes with a projected Deliot-style D3D12 update."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np

import fit_deliot_msaa_per_pixel_dev as base
from bench_component_gpu import select_adapter
from fit_projective_rgb_cpu import camera_sets


ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA256 = "b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c"
GEOMETRY_SHA256 = "3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe"
FIT_RECEIPT_SHA256 = "e11a1f18f79ead03f975e3cbda3e77354828f8f60be1a7d328f4912e8eb0e91a"
PROJECTION_TOLERANCE = 1e-6
PROJECTION_MAX_SWEEPS = 100


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_direction(direction, current, initial, faces, locked):
    """Hildreth projection onto linearized per-face normal-ratio constraints."""
    tri = current[faces].astype(np.float64)
    initial_tri = initial[faces].astype(np.float64)
    edge1, edge2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    initial_edge1 = initial_tri[:, 1] - initial_tri[:, 0]
    initial_edge2 = initial_tri[:, 2] - initial_tri[:, 0]
    reference = np.cross(initial_edge1, initial_edge2)
    normal = np.cross(edge1, edge2)
    denom = np.einsum("ij,ij->i", reference, reference)
    if np.any(denom <= 1e-30):
        raise ValueError("Initial mesh contains zero-area faces")

    constraint = (np.einsum("ij,ij->i", normal, reference) / denom
                  - base.NORMAL_FLOOR)
    jacobian = np.empty((len(faces), 3, 3), dtype=np.float64)
    jacobian[:, 0, :] = np.cross(reference, edge2 - edge1) / denom[:, None]
    jacobian[:, 1, :] = np.cross(edge2, reference) / denom[:, None]
    jacobian[:, 2, :] = np.cross(reference, edge1) / denom[:, None]
    for corner in range(3):
        jacobian[locked[faces[:, corner]], corner, :] = 0.0

    row_norm2 = np.einsum("fci,fci->f", jacobian, jacobian)
    if np.min(constraint) < -PROJECTION_TOLERANCE:
        raise ValueError("Current mesh is outside its frozen normal constraints")

    projected = direction.astype(np.float64).copy()
    projected[locked] = 0.0
    dual = np.zeros(len(faces), dtype=np.float64)
    rhs = -constraint
    sweeps = 0
    for sweep in range(PROJECTION_MAX_SWEEPS):
        for face_index, vertex_ids in enumerate(faces):
            norm2 = row_norm2[face_index]
            if norm2 <= 1e-30:
                continue
            row = jacobian[face_index]
            current_dot = float(np.sum(row * projected[vertex_ids]))
            new_dual = max(0.0, dual[face_index]
                           + (rhs[face_index] - current_dot) / norm2)
            delta = new_dual - dual[face_index]
            if delta:
                projected[vertex_ids] += delta * row
                dual[face_index] = new_dual
        sweeps = sweep + 1
        linearized = constraint + np.einsum(
            "fci,fci->f", jacobian, projected[faces])
        violation = max(0.0, float(-linearized.min()))
        if violation <= PROJECTION_TOLERANCE:
            break
    converged = violation <= PROJECTION_TOLERANCE
    diagnostics = {
        "converged": converged,
        "sweeps": sweeps,
        "minimum_linearized_constraint": float(linearized.min()),
        "maximum_linearized_violation": violation,
        "active_constraints": int(np.count_nonzero(dual > 0)),
        "projection_correction_l2": float(np.linalg.norm(projected - direction)),
        "projected_step_l2": float(np.linalg.norm(projected)),
    }
    projected[locked] = 0.0
    return projected.astype(np.float32), diagnostics


def fit_arm(raster, name, positions, faces, locked, views, references, seed):
    initial = positions.astype(np.float32).copy()
    current = initial.copy()
    locked = np.asarray(locked, dtype=bool)
    if locked.shape != (len(current),):
        raise ValueError(f"{name}: lock mask does not match vertex count")
    rng = np.random.default_rng(seed)
    m = np.zeros_like(current, dtype=np.float64)
    v = np.zeros_like(current, dtype=np.float64)
    trace = []
    fit_started = time.perf_counter()

    for iteration in range(base.UPDATES):
        before, per_view_before = base.train_loss(
            raster, current, faces, views, references)
        gradient = np.zeros_like(current, dtype=np.float64)
        per_view = []
        for view_index, (basis, reference) in enumerate(
                zip(views, references, strict=True)):
            _, base_ids = raster.render(current, faces, basis, with_ids=True)
            view_gradient = np.zeros_like(gradient)
            for _ in range(base.GRADIENT_SAMPLES):
                signs = rng.choice((-1., 1.), size=current.shape).astype(np.float32)
                signs[locked] = 0.0
                positive, _ = raster.render(
                    current + base.EPSILON * signs, faces, basis)
                negative, _ = raster.render(
                    current - base.EPSILON * signs, faces, basis)
                base.per_pixel_accumulate(view_gradient, base_ids, positive,
                                          negative, reference, faces, signs)
            gradient += view_gradient / base.GRADIENT_SAMPLES
            per_view.append({"view_index": view_index,
                             "gradient_l2": float(np.linalg.norm(view_gradient))})
        gradient /= len(views)
        gradient[locked] = 0.0

        m = 0.9 * m + 0.1 * gradient
        v = 0.999 * v + 0.001 * gradient * gradient
        m_hat = m / (1.0 - 0.9 ** (iteration + 1))
        v_hat = v / (1.0 - 0.999 ** (iteration + 1))
        adam_step = -base.EPSILON * m_hat / (np.sqrt(v_hat) + 1e-8)
        adam_step[locked] = 0.0
        step, projection = project_direction(
            adam_step, current, initial, faces, locked)
        row = {
            "iteration": iteration,
            "train_mse_before": before,
            "per_view_train_mse_before": per_view_before,
            "gradient_l2": float(np.linalg.norm(gradient)),
            "step_l2_max": float(np.linalg.norm(adam_step, axis=1).max()),
            "gradient_samples_per_view": base.GRADIENT_SAMPLES,
            "per_view_gradient_l2": per_view,
            "projection": projection,
            "accepted_halving": None,
            "train_mse_after": before,
            "line_search": [],
        }
        if projection["converged"]:
            for half in range(5):
                candidate = current + step * (0.5 ** half)
                offset = candidate - initial
                length = np.linalg.norm(offset, axis=1, keepdims=True)
                offset *= np.minimum(
                    1.0, base.MAX_DISPLACEMENT / np.maximum(length, 1e-30))
                candidate = initial + offset
                candidate[locked] = initial[locked]
                normal = base.normal_diagnostics(initial, candidate, faces)
                attempt = {"halving": half,
                           "minimum_face_normal_dot_ratio": normal[
                               "minimum_face_normal_dot_ratio"],
                           "degenerate_faces": normal["degenerate_faces"]}
                if normal["degenerate_faces"]:
                    attempt["rejection"] = "degenerate_faces"
                elif normal["minimum_face_normal_dot_ratio"] < base.NORMAL_FLOOR:
                    attempt["rejection"] = "normal_floor"
                else:
                    after, per_view_after = base.train_loss(
                        raster, candidate, faces, views, references)
                    attempt["training_mse_after"] = after
                    if after < before - 1e-12:
                        current = candidate
                        attempt["accepted"] = True
                        row.update(accepted_halving=half,
                                   train_mse_after=after,
                                   per_view_train_mse_after=per_view_after)
                    else:
                        attempt["rejection"] = "training_loss_not_improved"
                row["line_search"].append(attempt)
                if row["accepted_halving"] is not None:
                    break
        else:
            row["line_search"].append({
                "rejection": "projection_did_not_converge"})
        trace.append(row)

    diagnostics = base.normal_diagnostics(initial, current, faces)
    diagnostics.update({
        "maximum_displacement": float(np.linalg.norm(current - initial, axis=1).max()),
        "locked_vertices": int(np.count_nonzero(locked)),
        "locked_vertices_unchanged": bool(np.array_equal(
            current[locked], initial[locked])),
        "fit_seconds": time.perf_counter() - fit_started,
        "trace": trace,
    })
    return current, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--prior-receipt", type=Path, required=True)
    parser.add_argument("--fit-receipt", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run_started = time.perf_counter()

    prior = json.loads(args.prior_receipt.read_text(encoding="utf-8"))
    checks = {
        "geometry": digest(args.geometry) == GEOMETRY_SHA256
                    == prior["geometry_sha256"],
        "source": digest(args.source) == SOURCE_SHA256,
        "fit_receipt": digest(args.fit_receipt) == FIT_RECEIPT_SHA256,
    }
    if not all(checks.values()):
        parser.error(f"Frozen input hashes do not match: {checks}")

    arrays = np.load(args.geometry, allow_pickle=False)
    adapter = select_adapter("Intel(R) Iris(R) Xe Graphics", "D3D12")
    if adapter.info["adapter_type"] != "IntegratedGPU":
        raise RuntimeError(f"Refusing a software adapter: {dict(adapter.info)}")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    training_views, _ = camera_sets()
    diagnostic_cut = next(cut for cut in prior["cuts"]
                          if cut["face_count"] == 5290)
    diagnostic_views = diagnostic_cut["means_and_per_view"]["views"]
    all_bases = [np.asarray(basis, dtype=np.float64) for basis in training_views]
    all_bases.extend(np.asarray(view["basis"], dtype=np.float64)
                     for view in diagnostic_views)
    source = (arrays["source_positions"].astype(np.float32),
              arrays["source_faces"].astype(np.int64))
    arms = base.make_arms(arrays)
    high = base.Raster(device, base.SIZE * base.REFERENCE_SCALE,
                       base.SIZE * base.REFERENCE_SCALE, len(source[1]))
    low = base.Raster(device, base.SIZE, base.SIZE, 5290)

    references = []
    captures = {}
    for index, basis in enumerate(all_bases):
        image, _ = high.render(*source, basis)
        linear = image.astype(np.float32) / 255.0
        downsampled = linear.reshape(base.SIZE, 2, base.SIZE, 2, 4).mean(axis=(1, 3))
        references.append(downsampled[..., 0].copy())
        if index >= len(training_views):
            capture_index = index - len(training_views)
            captures[f"view_{capture_index:02d}_reference"] = base.linear_gray_to_srgb_u8(
                np.repeat(np.rint(downsampled[..., :1] * 255).astype(np.uint8),
                          3, axis=-1))

    output_geometry = {}
    arm_rows = {}
    for index, (name, (positions, faces, locked)) in enumerate(arms.items()):
        fitted, fit_report = fit_arm(
            low, name, positions, faces, locked, all_bases[:len(training_views)],
            references[:len(training_views)], base.SEED + index)
        output_geometry[f"{name}_raw_positions"] = positions
        output_geometry[f"{name}_faces"] = faces.astype(np.uint32)
        output_geometry[f"{name}_fit_positions"] = fitted
        output_geometry[f"{name}_locked"] = locked
        arm_rows[name] = {"initial_face_count": int(len(faces)),
                          "initial_vertex_count": int(len(positions)),
                          "fit": fit_report}
        print(json.dumps({"arm": name, "accepted_updates": sum(
            row["accepted_halving"] is not None for row in fit_report["trace"]),
            "projections_converged": all(
                row["projection"]["converged"] for row in fit_report["trace"])}),
            flush=True)

    image_rows = {"validation": []}
    for view_index, (basis, view) in enumerate(zip(
            all_bases[len(training_views):], diagnostic_views, strict=True)):
        row = {"view": int(view["view"]),
               "screen_scale": float(view["screen_scale"]),
               "basis": basis.tolist(), "arms": {}}
        reference = references[len(training_views) + view_index]
        reference_key = f"view_{view_index:02d}_reference"
        captured_reference = base.linear_gray_to_srgb_u8(
            np.repeat(np.rint(reference[..., None] * 255).astype(np.uint8),
                      3, axis=-1))
        captures[reference_key] = captured_reference
        row["reference_capture"] = reference_key
        row["reference_sha256"] = hashlib.sha256(
            captured_reference.tobytes()).hexdigest()
        for name, (positions, faces, _) in arms.items():
            row["arms"][name] = {}
            for variant, geometry in (
                    ("raw", positions),
                    ("fit", output_geometry[f"{name}_fit_positions"])):
                image, _ = low.render(geometry, faces, basis)
                capture_key = f"view_{view_index:02d}_{name}_{variant}"
                captured = base.linear_gray_to_srgb_u8(image)
                captures[capture_key] = captured
                row["arms"][name][variant] = {
                    "capture": capture_key,
                    "image_sha256": hashlib.sha256(captured.tobytes()).hexdigest(),
                    "silhouette_xor_fraction": float(np.mean(
                        (reference > 0) != (image[..., 0] > 0))),
                }
        image_rows["validation"].append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    geometry_path = args.out.with_name("result.geometry.npz")
    with geometry_path.open("wb") as stream:
        np.savez_compressed(stream, source_positions=source[0],
                            source_faces=source[1].astype(np.uint32), **output_geometry)
    capture_path = args.out.with_name("result.captures.npz")
    with capture_path.open("wb") as stream:
        np.savez_compressed(stream, **captures)
    protocol = ROOT / "tools/mmtrain/DELIOT_ACTIVE_NORMAL_PROJECTION_DEV_PROTOCOL_20261127.md"
    receipt = {
        "status": "capture_complete",
        "scope": "one-asset active-normal projected stochastic fit development screen",
        "input_hash_checks": checks,
        "source_sha256": digest(args.source),
        "geometry_sha256": digest(args.geometry),
        "prior_receipt_sha256": digest(args.prior_receipt),
        "fit_receipt_sha256": digest(args.fit_receipt),
        "protocol_sha256": digest(protocol),
        "script_sha256": digest(__file__),
        "base_fit_script_sha256": digest(ROOT / "tools/mmtrain/fit_deliot_msaa_per_pixel_dev.py"),
        "adapter": dict(adapter.info),
        "wgpu_version": importlib.metadata.version("wgpu"),
        "resolution": [base.SIZE, base.SIZE],
        "reference_resolution": [base.SIZE * 2, base.SIZE * 2],
        "sample_count": base.SAMPLE_COUNT,
        "epsilon": base.EPSILON,
        "gradient_samples_per_update": base.GRADIENT_SAMPLES,
        "updates": base.UPDATES,
        "projection_tolerance": PROJECTION_TOLERANCE,
        "projection_max_sweeps": PROJECTION_MAX_SWEEPS,
        "training_camera_bases": [np.asarray(b).tolist() for b in training_views],
        "diagnostic_views": [{"view": int(v["view"]), "basis": v["basis"],
                              "screen_scale": v["screen_scale"]}
                             for v in diagnostic_views],
        "arms": arm_rows,
        "image_rows": image_rows,
        "render_count": {"high_reference": high.render_count,
                         "low_candidate_and_fit": low.render_count},
        "elapsed_seconds": time.perf_counter() - run_started,
        "geometry_archive": str(geometry_path),
        "geometry_archive_sha256": digest(geometry_path),
        "capture_archive": str(capture_path),
        "capture_archive_sha256": digest(capture_path),
        "diagnostic_views_are_correlated_and_previously_scored": True,
        "limitations": ["single reused train asset",
                        "diagnostic views previously scored",
                        "no asset-held-out confirmation", "flat grayscale shader",
                        "no mobile device", "no equal-frame-time comparison"],
    }
    args.out.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"status": receipt["status"],
                      "render_count": receipt["render_count"],
                      "elapsed_seconds": receipt["elapsed_seconds"],
                      "capture_archive_sha256": receipt["capture_archive_sha256"]},
                     separators=(",", ":"), allow_nan=False), flush=True)


if __name__ == "__main__":
    main()

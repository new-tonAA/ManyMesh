"""Feasibility screen using exact fraction-to-boundary Adam steps on D3D12."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

import fit_deliot_active_normal_projection as active
import fit_deliot_msaa_per_pixel_dev as base
from bench_component_gpu import select_adapter
from fit_projective_rgb_cpu import camera_sets


ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_SHA256 = "3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe"
SOURCE_SHA256 = "b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c"
FIT_RECEIPT_SHA256 = "e11a1f18f79ead03f975e3cbda3e77354828f8f60be1a7d328f4912e8eb0e91a"
STRICT_FRACTION = 0.9
ROOT_EPSILON = 1e-12


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def first_feasible_exit(c, b, a):
    """Return the earliest fraction in (0, 1] where c+b*t+a*t² reaches 0."""
    c, b, a = float(c), float(b), float(a)
    if c < -1e-10:
        raise ValueError(f"Starting point is infeasible: constraint={c}")
    if c <= 1e-10:
        if b < -1e-12 or (abs(b) <= 1e-12 and a < -1e-12):
            return 0.0
    roots = []
    if abs(a) <= 1e-18:
        if abs(b) > 1e-18:
            roots.append(-c / b)
    else:
        discriminant = b * b - 4.0 * a * c
        if discriminant >= 0.0:
            root = np.sqrt(discriminant)
            roots.extend(((-b - root) / (2.0 * a),
                          (-b + root) / (2.0 * a)))
    positive = [t for t in roots if ROOT_EPSILON < t <= 1.0]
    return min(positive) if positive else 1.0


def fraction_to_boundary(step, current, initial, faces):
    """Bound one global step by exact quadratic face and displacement limits."""
    x = current[faces].astype(np.float64)
    x0 = initial[faces].astype(np.float64)
    d = step[faces].astype(np.float64)
    e1, e2 = x[:, 1] - x[:, 0], x[:, 2] - x[:, 0]
    de1, de2 = d[:, 1] - d[:, 0], d[:, 2] - d[:, 0]
    n0 = np.cross(x0[:, 1] - x0[:, 0], x0[:, 2] - x0[:, 0])
    denom = np.einsum("ij,ij->i", n0, n0)
    if np.any(denom <= 1e-30):
        raise ValueError("Initial geometry contains a zero-area face")
    normal_c = np.einsum("ij,ij->i", np.cross(e1, e2), n0) / denom
    normal_b = np.einsum("ij,ij->i", np.cross(de1, e2)
                         + np.cross(e1, de2), n0) / denom
    normal_a = np.einsum("ij,ij->i", np.cross(de1, de2), n0) / denom

    fraction = 1.0
    limiting = {"kind": "none", "index": None, "unshrunk_fraction": 1.0}
    for face_index, (c, b, a) in enumerate(zip(
            normal_c - base.NORMAL_FLOOR, normal_b, normal_a, strict=True)):
        root = first_feasible_exit(c, b, a)
        if root < fraction:
            fraction = root
            limiting = {"kind": "face_normal", "index": face_index,
                        "unshrunk_fraction": float(root)}

    offset = current.astype(np.float64) - initial.astype(np.float64)
    direction = step.astype(np.float64)
    for vertex in range(len(current)):
        c = base.MAX_DISPLACEMENT**2 - float(np.dot(offset[vertex], offset[vertex]))
        b = -2.0 * float(np.dot(offset[vertex], direction[vertex]))
        a = -float(np.dot(direction[vertex], direction[vertex]))
        root = first_feasible_exit(c, b, a)
        if root < fraction:
            fraction = root
            limiting = {"kind": "displacement", "index": vertex,
                        "unshrunk_fraction": float(root)}

    if fraction < 1.0:
        fraction *= STRICT_FRACTION
    return float(min(1.0, fraction)), limiting


def fit_arm(raster, name, positions, faces, locked, views, references, seed):
    initial = positions.astype(np.float32).copy()
    current = initial.copy()
    locked = np.asarray(locked, dtype=bool)
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
        step = -base.EPSILON * m_hat / (np.sqrt(v_hat) + 1e-8)
        step[locked] = 0.0
        alpha, limiting = fraction_to_boundary(step, current, initial, faces)
        step *= alpha

        row = {"iteration": iteration, "train_mse_before": before,
               "per_view_train_mse_before": per_view_before,
               "gradient_l2": float(np.linalg.norm(gradient)),
               "step_l2_max": float(np.linalg.norm(step, axis=1).max()),
               "gradient_samples_per_view": base.GRADIENT_SAMPLES,
               "per_view_gradient_l2": per_view,
               "safe_fraction": alpha, "limiting_constraint": limiting,
               "accepted_halving": None, "train_mse_after": before,
               "line_search": []}
        for half in range(5):
            candidate = current + step * (0.5 ** half)
            candidate[locked] = initial[locked]
            displacement = np.linalg.norm(candidate - initial, axis=1)
            normal = base.normal_diagnostics(initial, candidate, faces)
            attempt = {"halving": half,
                       "maximum_displacement": float(displacement.max()),
                       **normal}
            if normal["degenerate_faces"]:
                attempt["rejection"] = "degenerate_faces"
            elif displacement.max() > base.MAX_DISPLACEMENT + 1e-7:
                attempt["rejection"] = "displacement_limit"
            elif normal["minimum_face_normal_dot_ratio"] < base.NORMAL_FLOOR - 1e-7:
                attempt["rejection"] = "normal_floor"
            else:
                after, per_view_after = base.train_loss(
                    raster, candidate, faces, views, references)
                attempt["training_mse_after"] = after
                if after < before - 1e-12:
                    current = candidate
                    attempt["accepted"] = True
                    row.update(accepted_halving=half, train_mse_after=after,
                               per_view_train_mse_after=per_view_after)
                else:
                    attempt["rejection"] = "training_loss_not_improved"
            row["line_search"].append(attempt)
            if row["accepted_halving"] is not None:
                break
        trace.append(row)
        print(json.dumps({"arm": name, "update": iteration,
                          "alpha": alpha,
                          "accepted": row["accepted_halving"] is not None,
                          "mse_before": before,
                          "mse_after": row["train_mse_after"]}), flush=True)

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
    source = (arrays["source_positions"].astype(np.float32),
              arrays["source_faces"].astype(np.int64))
    arms = base.make_arms(arrays)
    high = base.Raster(device, base.SIZE * base.REFERENCE_SCALE,
                       base.SIZE * base.REFERENCE_SCALE, len(source[1]))
    low = base.Raster(device, base.SIZE, base.SIZE, 5290)

    references = []
    for basis in training_views:
        image, _ = high.render(*source, basis)
        linear = image.astype(np.float32) / 255.0
        downsampled = linear.reshape(base.SIZE, 2, base.SIZE, 2, 4).mean(axis=(1, 3))
        references.append(downsampled[..., 0].copy())

    arm_rows = {}
    for index, (name, (positions, faces, locked)) in enumerate(arms.items()):
        fitted, fit_report = fit_arm(
            low, name, positions, faces, locked, training_views,
            references, base.SEED + index)
        arm_rows[name] = {
            "initial_face_count": int(len(faces)),
            "initial_vertex_count": int(len(positions)),
            "fitted_positions_sha256": hashlib.sha256(
                np.ascontiguousarray(fitted).tobytes()).hexdigest(),
            "fit": fit_report,
        }

    protocol = ROOT / "tools/mmtrain/DELIOT_EXACT_FRACTION_TO_BOUNDARY_DEV_PROTOCOL_20261127.md"
    receipt = {
        "status": "feasibility_complete",
        "scope": "one-asset exact fraction-to-boundary training-feasibility screen",
        "input_hash_checks": checks,
        "geometry_sha256": digest(args.geometry),
        "source_sha256": digest(args.source),
        "fit_receipt_sha256": digest(args.fit_receipt),
        "protocol_sha256": digest(protocol),
        "script_sha256": digest(__file__),
        "active_projection_script_sha256": digest(
            ROOT / "tools/mmtrain/fit_deliot_active_normal_projection.py"),
        "base_fit_script_sha256": digest(
            ROOT / "tools/mmtrain/fit_deliot_msaa_per_pixel_dev.py"),
        "adapter": dict(adapter.info),
        "wgpu_version": base.importlib.metadata.version("wgpu"),
        "training_views": len(training_views),
        "resolution": [base.SIZE, base.SIZE],
        "sample_count": base.SAMPLE_COUNT,
        "gradient_samples_per_update": base.GRADIENT_SAMPLES,
        "updates": base.UPDATES,
        "strict_fraction": STRICT_FRACTION,
        "arms": arm_rows,
        "render_count": {"high_reference": high.render_count,
                         "low_candidate_and_fit": low.render_count},
        "elapsed_seconds": time.perf_counter() - run_started,
        "decision_gate": "each arm must accept at least 3 of 4 updates and pass all structural checks",
        "image_quality_scored": False,
        "limitations": ["single reused train asset", "training loss only",
                        "no held-out image quality", "no mobile device",
                        "no equal-frame-time comparison"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"status": receipt["status"],
                      "render_count": receipt["render_count"],
                      "elapsed_seconds": receipt["elapsed_seconds"],
                      "output": str(args.out)}, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()

"""Replay the frozen Deliot-style fit and log why line-search trials are rejected."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmtrain"))
import fit_deliot_msaa_per_pixel_dev as fit  # noqa: E402
from bench_component_gpu import select_adapter  # noqa: E402
from fit_projective_rgb_cpu import camera_sets  # noqa: E402


SOURCE_SHA256 = "b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c"
GEOMETRY_SHA256 = "3403b80d4868eb483b6c97e0bcef4d30b97332833653be55faead9af3888ecbe"
FIT_RECEIPT_SHA256 = "e11a1f18f79ead03f975e3cbda3e77354828f8f60be1a7d328f4912e8eb0e91a"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replay_arm(raster, name, positions, faces, locked, views, references, seed):
    initial = positions.astype(np.float32).copy()
    current = initial.copy()
    locked = np.asarray(locked, dtype=bool)
    rng = np.random.default_rng(seed)
    m = np.zeros_like(current, dtype=np.float64)
    v = np.zeros_like(current, dtype=np.float64)
    trace = []

    for iteration in range(fit.UPDATES):
        before, _ = fit.train_loss(raster, current, faces, views, references)
        gradient = np.zeros_like(current, dtype=np.float64)
        for basis, reference in zip(views, references, strict=True):
            _, base_ids = raster.render(current, faces, basis, with_ids=True)
            view_gradient = np.zeros_like(gradient)
            for _ in range(fit.GRADIENT_SAMPLES):
                signs = rng.choice((-1., 1.), size=current.shape).astype(np.float32)
                signs[locked] = 0.
                positive, _ = raster.render(current + fit.EPSILON * signs,
                                            faces, basis)
                negative, _ = raster.render(current - fit.EPSILON * signs,
                                            faces, basis)
                fit.per_pixel_accumulate(view_gradient, base_ids, positive,
                                         negative, reference, faces, signs)
            gradient += view_gradient / fit.GRADIENT_SAMPLES
        gradient /= len(views)
        gradient[locked] = 0.

        m = 0.9 * m + 0.1 * gradient
        v = 0.999 * v + 0.001 * gradient * gradient
        m_hat = m / (1.0 - 0.9 ** (iteration + 1))
        v_hat = v / (1.0 - 0.999 ** (iteration + 1))
        step = -fit.EPSILON * m_hat / (np.sqrt(v_hat) + 1e-8)
        step[locked] = 0.

        attempts = []
        accepted = False
        for half in range(5):
            candidate = current + step * (0.5 ** half)
            offset = candidate - initial
            length = np.linalg.norm(offset, axis=1, keepdims=True)
            offset *= np.minimum(1.0, fit.MAX_DISPLACEMENT /
                                 np.maximum(length, 1e-30))
            candidate = initial + offset
            candidate[locked] = initial[locked]
            normal = fit.normal_diagnostics(initial, candidate, faces)
            attempt = {
                "halving": half,
                "minimum_face_normal_dot_ratio": normal["minimum_face_normal_dot_ratio"],
                "degenerate_faces": normal["degenerate_faces"],
                "rejection": None,
            }
            if normal["degenerate_faces"]:
                attempt["rejection"] = "degenerate_faces"
            elif normal["minimum_face_normal_dot_ratio"] < fit.NORMAL_FLOOR:
                attempt["rejection"] = "normal_floor"
            else:
                after, _ = fit.train_loss(raster, candidate, faces, views,
                                          references)
                attempt["training_mse_after"] = after
                if after < before - 1e-12:
                    attempt["accepted"] = True
                    accepted = True
                    current = candidate
                else:
                    attempt["rejection"] = "training_loss_not_improved"
            attempts.append(attempt)
            if accepted:
                break

        trace.append({
            "iteration": iteration,
            "training_mse_before": before,
            "gradient_l2": float(np.linalg.norm(gradient)),
            "maximum_vertex_step": float(np.linalg.norm(step, axis=1).max()),
            "attempts": attempts,
            "update_accepted": accepted,
        })

    return current, trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--prior-receipt", type=Path, required=True)
    parser.add_argument("--fit-receipt", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    checks = {
        "source": digest(args.source) == SOURCE_SHA256,
        "geometry": digest(args.geometry) == GEOMETRY_SHA256,
        "fit_receipt": digest(args.fit_receipt) == FIT_RECEIPT_SHA256,
    }
    prior = json.loads(args.prior_receipt.read_text(encoding="utf-8"))
    if not all(checks.values()) or digest(args.geometry) != prior["geometry_sha256"]:
        raise ValueError(f"Frozen input hash mismatch: {checks}")

    arrays = np.load(args.geometry, allow_pickle=False)
    adapter = select_adapter("Intel(R) Iris(R) Xe Graphics", "D3D12")
    if adapter.info["adapter_type"] != "IntegratedGPU":
        raise RuntimeError(f"Refusing non-hardware adapter: {dict(adapter.info)}")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    training_views, _ = camera_sets()
    source = (arrays["source_positions"].astype(np.float32),
              arrays["source_faces"].astype(np.int64))
    arms = fit.make_arms(arrays)
    high = fit.Raster(device, fit.SIZE * fit.REFERENCE_SCALE,
                      fit.SIZE * fit.REFERENCE_SCALE, len(source[1]))
    low = fit.Raster(device, fit.SIZE, fit.SIZE, 5290)

    references = []
    for basis in training_views:
        image, _ = high.render(*source, basis)
        linear = image.astype(np.float32) / 255.0
        downsampled = linear.reshape(fit.SIZE, 2, fit.SIZE, 2, 4).mean(axis=(1, 3))
        references.append(downsampled[..., 0].copy())

    started = time.perf_counter()
    arm_rows = {}
    output_geometry = {}
    for index, (name, (positions, faces, locked)) in enumerate(arms.items()):
        fitted, trace = replay_arm(
            low, name, positions, faces, locked, training_views, references,
            fit.SEED + index)
        output_geometry[name] = {
            "initial_positions_sha256": hashlib.sha256(positions.tobytes()).hexdigest(),
            "replayed_positions_sha256": hashlib.sha256(fitted.tobytes()).hexdigest(),
            "positions_unchanged": bool(np.array_equal(positions, fitted)),
            "face_count": int(len(faces)),
            "updates_accepted": sum(int(row["update_accepted"]) for row in trace),
            "trace": trace,
        }
        arm_rows[name] = output_geometry[name]

    rejection_counts = {}
    for arm in arm_rows.values():
        for update in arm["trace"]:
            for attempt in update["attempts"]:
                reason = attempt["rejection"] or "accepted"
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    protocol_path = ROOT / "tools/mmtrain/DELIOT_FIT_REJECTION_DIAGNOSTIC_PROTOCOL_20261127.md"
    receipt = {
        "status": "diagnostic_complete",
        "scope": "instrumented deterministic replay; no quality scoring",
        "protocol_sha256": digest(protocol_path),
        "diagnostic_script_sha256": digest(__file__),
        "fit_script_sha256": digest(ROOT / "tools/mmtrain/fit_deliot_msaa_per_pixel_dev.py"),
        "source_sha256": digest(args.source),
        "geometry_sha256": digest(args.geometry),
        "prior_receipt_sha256": digest(args.prior_receipt),
        "fit_receipt_sha256": digest(args.fit_receipt),
        "adapter": dict(adapter.info),
        "wgpu_version": importlib.metadata.version("wgpu"),
        "camera_count": len(training_views),
        "renders": {"reference": high.render_count, "fit": low.render_count},
        "elapsed_seconds": time.perf_counter() - started,
        "rejection_counts": rejection_counts,
        "arms": arm_rows,
        "quality_scored": False,
        "limitations": [
            "single reused train asset",
            "replay is diagnostic only and does not establish image-quality gain",
            "does not evaluate the previously scored diagnostic views",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"status": receipt["status"],
                      "renders": receipt["renders"],
                      "rejection_counts": rejection_counts,
                      "elapsed_seconds": receipt["elapsed_seconds"]},
                     separators=(",", ":"), allow_nan=False), flush=True)


if __name__ == "__main__":
    main()

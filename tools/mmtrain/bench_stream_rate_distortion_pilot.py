"""Run the frozen one-asset progressive LOD byte/quality pilot."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmgeo"))
sys.path.insert(0, str(ROOT / "tools/mmtrain"))

from bench_geometry_codecs import BITS, checked_mesh, run_codecs, score_codec
from cluster_decoder_pilot import read_stl
from cluster_decoder_quality import render
from compare_qem_meshopt_validation_70pct import image_metrics, meshopt_simplify_raw
from make_refinement_pairs import view_basis


PAGE_SIZES = (1024, 4096, 16384, 65536, 262144)
VIEWS = 8
SIZE = 192
SAMPLES = 2
FLIP_PPD = 67.0
FACE_TARGET = 5290
ASSET_ID = 84736


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cpu_model():
    if platform.processor():
        return platform.processor()
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def load_binary_xyz_ply(path):
    scalar_types = {"char": "i1", "uchar": "u1", "short": "<i2", "ushort": "<u2",
                    "int": "<i4", "uint": "<u4", "float": "<f4", "double": "<f8"}
    with Path(path).open("rb") as stream:
        header = []
        while True:
            line = stream.readline()
            if not line:
                raise ValueError(f"unterminated PLY header: {path}")
            header.append(line.decode("ascii").strip())
            if header[-1] == "end_header":
                break
        if "format binary_little_endian 1.0" not in header:
            raise ValueError("Expected binary little-endian PLY")
        vertex_count = next(int(line.split()[2]) for line in header
                            if line.startswith("element vertex "))
        face_count = next(int(line.split()[2]) for line in header
                          if line.startswith("element face "))
        vertex_properties = []
        face_properties = []
        active_element = None
        for line in header:
            if line.startswith("element vertex "):
                active_element = "vertex"
            elif line.startswith("element face "):
                active_element = "face"
            elif line.startswith("element "):
                active_element = None
            elif line.startswith("property ") and active_element == "vertex":
                fields = line.split()
                if len(fields) != 3 or fields[1] not in scalar_types:
                    raise ValueError(f"Unsupported PLY vertex property: {line}")
                vertex_properties.append((fields[2], scalar_types[fields[1]]))
            elif line.startswith("property ") and active_element == "face":
                face_properties.append(line.split())
        names = [name for name, _dtype in vertex_properties]
        if not all(name in names for name in ("x", "y", "z")):
            raise ValueError(f"PLY has no XYZ vertex fields: {names}")
        dtype = np.dtype(vertex_properties)
        vertex_bytes = stream.read(dtype.itemsize * vertex_count)
        if len(vertex_bytes) != dtype.itemsize * vertex_count:
            raise ValueError("Truncated PLY vertex array")
        records = np.frombuffer(vertex_bytes, dtype=dtype, count=vertex_count)
        positions = np.column_stack((records["x"], records["y"], records["z"])).astype(np.float64)
        lists = [item for item in face_properties if len(item) == 5 and item[1] == "list"]
        if len(lists) != 1:
            raise ValueError(f"Expected one PLY face index list: {face_properties}")
        scalar_face_properties = [item for item in face_properties if len(item) == 3]
        if any(item[1] not in scalar_types for item in scalar_face_properties):
            raise ValueError(f"Unsupported PLY scalar face property: {scalar_face_properties}")
        _property, _list, count_type, index_type, _name = lists[0]
        if count_type not in scalar_types or index_type not in scalar_types:
            raise ValueError("Unsupported PLY face index types")
        count_dtype = np.dtype(scalar_types[count_type])
        index_dtype = np.dtype(scalar_types[index_type])
        faces = np.empty((face_count, 3), dtype=np.int64)
        for face_id in range(face_count):
            raw_count = stream.read(count_dtype.itemsize)
            if len(raw_count) != count_dtype.itemsize:
                raise ValueError("Truncated PLY face count")
            count = int(np.frombuffer(raw_count, dtype=count_dtype, count=1)[0])
            if count != 3:
                raise ValueError("Expected triangular faces")
            raw_indices = stream.read(index_dtype.itemsize * 3)
            if len(raw_indices) != index_dtype.itemsize * 3:
                raise ValueError("Truncated PLY face indices")
            faces[face_id] = np.frombuffer(raw_indices, dtype=index_dtype, count=3)
            extra_bytes = sum(np.dtype(scalar_types[item[1]]).itemsize
                              for item in scalar_face_properties)
            if len(stream.read(extra_bytes)) != extra_bytes:
                raise ValueError("Truncated PLY scalar face properties")
    if not np.isfinite(positions).all() or (faces.size and
            (faces.min() < 0 or faces.max() >= vertex_count)):
        raise ValueError("Invalid PLY geometry")
    return positions, faces


def normalized(positions, center, radius):
    return ((positions - center) / radius).astype(np.float32).astype(np.float64)


def mesh_record(positions, triangles):
    mesh, boundary = checked_mesh(positions, triangles)
    return {"vertices": len(mesh.positions), "faces": len(mesh.triangles),
            "boundary_edges": len(boundary),
            "boundary_directed": [
                [list(start), list(end)] for _cluster, start, end in boundary]}


def score_geometry(geometry, captured, bases):
    rows = []
    for basis, (reference, reference_coverage) in zip(bases, captured):
        image, coverage = render(*geometry, basis, SIZE, SAMPLES)
        rows.append(image_metrics(reference, image, reference_coverage, coverage, FLIP_PPD))
    mean = {key: float(np.mean([row[key] for row in rows]))
            for key in ("mse", "ssim", "flip", "coverage_mae",
                        "silhouette_xor_fraction")}
    mean["psnr_db"] = None if mean["mse"] == 0 else -10 * float(np.log10(mean["mse"]))
    return {"per_view": rows, "mean": mean}


def mmb_page_accounting(blob_path, graph_path):
    blob = Path(blob_path).read_bytes()
    graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    node_count = int(graph["nodes"])
    root_count = len(graph["roots"])
    leaf_count = len(graph["leaves"])
    cursor = 36 + 4 * (root_count + leaf_count)
    generated_count, = struct.unpack_from("<I", blob, cursor)
    cursor += 4 + generated_count * 40
    position_count, = struct.unpack_from("<I", blob, cursor)
    cursor += 4 + position_count * 4
    offsets = struct.unpack_from(f"<{node_count + 1}Q", blob, cursor)
    if offsets[0] < cursor + (node_count + 1) * 8 or offsets[-1] != len(blob):
        raise ValueError("MMLG v7 offset table does not match the serialized blob")
    selected_nodes = [int(node) for node in graph["selectedNodes"]]
    source_vertices = int(graph["sourceVertices"])
    selected_source_vertices = set()
    selected_generated_vertices = set()
    node_bytes = 0
    for node_id in selected_nodes:
        if not 0 <= node_id < node_count:
            raise ValueError(f"Selected node ID out of range: {node_id}")
        start = offsets[node_id]
        child_count, index_count = struct.unpack_from("<II", blob, start + 16)
        indices_offset = start + 184 + 4 * child_count
        indices = struct.unpack_from(f"<{index_count}I", blob, indices_offset)
        node_bytes += offsets[node_id + 1] - start
        selected_source_vertices.update(index for index in indices if index < source_vertices)
        selected_generated_vertices.update(index for index in indices if index >= source_vertices)

    result = {
        "mmb_sha256": digest(blob_path), "graph_json_sha256": digest(graph_path),
        "node_count": node_count, "selected_node_count": len(selected_nodes),
        "selected_nodes": selected_nodes,
        "selected_face_count": int(graph["selectedTriangles"]),
        "source_vertex_table_count": position_count,
        "source_vertices": source_vertices, "generated_vertices": generated_count,
        "selected_unique_source_vertices": len(selected_source_vertices),
        "selected_generated_vertices_referenced": len(selected_generated_vertices),
        "metadata_prefix_bytes_through_node_offsets": int(offsets[0]),
        "selected_node_record_bytes": int(node_bytes),
        "sparse_source_position_bytes_float32_xyz": 12 * len(selected_source_vertices),
        "page_sizes": {},
    }
    for page_size in PAGE_SIZES:
        pages = []
        first = 0
        while first < node_count:
            start = offsets[first]
            last = first
            while last + 2 <= node_count and offsets[last + 2] - start <= page_size:
                last += 1
            end = last + 1
            pages.append((first, end, start, offsets[end]))
            first = end
        selected_pages = [index for index, (first, end, _start, _stop) in enumerate(pages)
                          if any(first <= node_id < end for node_id in selected_nodes)]
        payload_bytes = sum(pages[index][3] - pages[index][2] for index in selected_pages)
        request_count = len(selected_pages)
        result["page_sizes"][str(page_size)] = {
            "range_request_count": request_count,
            "selected_page_payload_bytes": int(payload_bytes),
            "complete_geometry_bytes_lower_bound": int(
                offsets[0] + payload_bytes + 12 * len(selected_source_vertices)),
            "selected_page_indices": selected_pages,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True,
                        help="Folder containing the licensed source STL")
    parser.add_argument("--candidate-dir", type=Path, required=True,
                        help="Folder containing source.obj and generated MMLG/PLY files")
    parser.add_argument("--mmgeo", type=Path, required=True,
                        help="Exact DAG generator executable used for this candidate")
    parser.add_argument("--mmgeo-source-revision", required=True,
                        help="Git revision of the checkout used to build mmgeo")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = [asset for asset in manifest["files"] if asset["file_id"] == ASSET_ID]
    if len(assets) != 1 or assets[0]["split"] != "train":
        raise ValueError("Frozen asset 84736 must occur once and remain in the train split")
    asset = assets[0]
    source_path = args.asset_root / asset["path"]
    graph_path = args.candidate_dir / "lod_graph.json"
    blob_path = args.candidate_dir / "lod_graph.mmb"
    candidate_path = args.candidate_dir / "selected_ratio_0.5.ply"
    obj_path = args.candidate_dir / "source.obj"
    if digest(source_path) != asset["sha256"]:
        raise ValueError("Source STL hash does not match the frozen manifest")
    positions, triangles = read_stl(source_path)
    if len(triangles) != 10580 or int(asset["faces"]) != 10580:
        raise ValueError("Unexpected source face count")
    center = (positions.min(axis=0) + positions.max(axis=0)) * .5
    radius = np.linalg.norm(positions - center, axis=1).max()
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("Invalid source normalization radius")
    source = (normalized(positions, center, radius), triangles)
    _source_mesh, source_boundary = checked_mesh(*source)

    candidate_positions, candidate_triangles = load_binary_xyz_ply(candidate_path)
    candidate = (normalized(candidate_positions, center, radius), candidate_triangles)
    _candidate_mesh, candidate_boundary = checked_mesh(*candidate)
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if len(candidate_triangles) != FACE_TARGET or int(graph["selectedTriangles"]) != FACE_TARGET:
        raise ValueError("The candidate is not the frozen exact 5,290-face cut")
    candidate_boundary_equal = candidate_boundary == source_boundary

    temporary_root = args.out.parent
    args.out.parent.mkdir(parents=True, exist_ok=True)
    meshopt_positions, meshopt_triangles, meshopt_info = meshopt_simplify_raw(
        source[0], source[1], FACE_TARGET, temporary_root)
    if len(meshopt_triangles) != FACE_TARGET:
        raise ValueError(f"meshoptimizer missed exact face target: {len(meshopt_triangles)}")
    meshopt_geometry = (meshopt_positions, meshopt_triangles)
    _meshopt_mesh, meshopt_boundary = checked_mesh(*meshopt_geometry)
    meshopt_boundary_equal = meshopt_boundary == source_boundary

    bases = [view_basis(view, VIEWS) for view in range(VIEWS)]
    captured = [render(*source, basis, SIZE, SAMPLES) for basis in bases]
    raw_scores = {
        "source": score_geometry(source, captured, bases),
        "meshopt_exact_50": score_geometry(meshopt_geometry, captured, bases),
        "manymesh_50": score_geometry(candidate, captured, bases),
    }
    page = mmb_page_accounting(blob_path, graph_path)
    page["asset_id"] = ASSET_ID
    page["requested_64k_page_size_bytes"] = 65536
    candidate_bytes = page["page_sizes"]["65536"]["complete_geometry_bytes_lower_bound"]
    candidate_flip = raw_scores["manymesh_50"]["mean"]["flip"]
    windows_node = Path(os.environ.get("MANYMESH_WINDOWS_NODE", "/mnt/d/Nodejs/node.exe"))

    codec_rows = []
    geometries = (("full_source", source), ("meshopt_exact_50", meshopt_geometry))
    source_boundary_count = len(source_boundary)
    for label, geometry in geometries:
        input_mesh, input_boundary = checked_mesh(*geometry)
        encoded = run_codecs(*geometry, temporary_root)
        for result in encoded["results"]:
            decoded_vertices = result.get("positions")
            decoded_faces = result.get("indices")
            if decoded_vertices is not None and decoded_faces is not None:
                try:
                    decoded_mesh, decoded_boundary = checked_mesh(
                        np.asarray(decoded_vertices, dtype=np.float64).reshape(-1, 3),
                        np.asarray(decoded_faces, dtype=np.int64).reshape(-1, 3))
                    result["decoded_boundary_edges"] = len(decoded_boundary)
                    result["decoded_boundary_count_matches_input"] = (
                        len(decoded_boundary) == len(input_boundary))
                    result["decoded_faces"] = len(decoded_mesh.triangles)
                    result["decoded_vertices"] = len(decoded_mesh.positions)
                except ValueError as error:
                    result["decoded_boundary_count_matches_input"] = False
                    result["pre_score_topology_error"] = str(error)
            result["input"] = label
            result["input_faces"] = len(geometry[1])
            result["input_topology_eligible"] = (
                True if label == "full_source" else meshopt_boundary_equal)
            result["input_boundary_edges"] = len(input_boundary)
            row = score_codec(result, geometry, captured, bases, SIZE,
                              np.asarray(encoded["origin"]), encoded["range"])
            row["decoded_topology_eligible"] = (
                row["input_topology_eligible"] is True
                and "topology_error" not in row
                and row.get("oriented_grid_faces_match") is True
                and row.get("decoded_boundary_count_matches_input") is True)
            row["complete_geometry_bytes"] = row.get("bytes")
            codec_rows.append(row)

    eligible = [row for row in codec_rows
                if row.get("input_topology_eligible") is True
                and row.get("decoded_topology_eligible") is True
                and row.get("mean", {}).get("flip") is not None
                and abs(row["mean"]["flip"] - candidate_flip) <= 0.001]
    best_static = min(eligible, key=lambda row: row["complete_geometry_bytes"]) if eligible else None
    savings = (None if best_static is None else
               1.0 - candidate_bytes / best_static["complete_geometry_bytes"])
    dominators = [row for row in codec_rows
                  if row.get("input_topology_eligible") is True
                  and row.get("decoded_topology_eligible") is True
                  and row.get("decoded_faces") == FACE_TARGET
                  and row.get("complete_geometry_bytes", candidate_bytes) < candidate_bytes
                  and row.get("mean", {}).get("flip", candidate_flip) < candidate_flip]
    dominators.sort(key=lambda row: row["complete_geometry_bytes"])
    strongest_dominator = dominators[0] if dominators else None
    simplified_receipt = {key: meshopt_info[key] for key in (
        "error", "inputTriangles", "requestedTriangles", "outputTriangles", "flags")
        if key in meshopt_info}
    report = {
        "scope": "Frozen single-asset train-split development pilot; no test assets used",
        "status": "complete",
        "protocol": {"asset_id": ASSET_ID, "asset_split": "train", "views": VIEWS,
                     "image_size": [SIZE, SIZE], "supersamples_per_axis": SAMPLES,
                     "flip_ppd": FLIP_PPD, "face_target": FACE_TARGET,
                     "codec_bits": list(BITS), "meshopt_header_bytes": 32,
                     "quality_matching_tolerance_abs_mean_flip": 0.001,
                     "required_byte_savings": 0.10},
        "asset": {"file_id": ASSET_ID, "thing_id": asset["thing_id"],
                  "license": asset["license"], "source_url": asset["source_url"],
                  "source_sha256": digest(source_path), "source_bytes": source_path.stat().st_size,
                  "source_faces": len(source[1]), "source_vertices": len(source[0]),
                  "normalization_center": center.tolist(), "normalization_radius": float(radius),
                  "derived_obj_sha256": digest(obj_path)},
        "manifest_sha256": digest(args.manifest),
        "generator": {"executable_path": str(args.mmgeo),
                      "executable_sha256": digest(args.mmgeo),
                      "source_revision": args.mmgeo_source_revision,
                      "source_file_sha256": digest(ROOT / "tools/mmgeo/src/main.cpp"),
                      "generation_command": ["mmgeo", "source.obj", "--out", "<candidate-dir>",
                                             "--mode", "dag", "--target-ratio-cut",
                                             "0.75,0.5,0.25", "--page-bytes", "65536"]},
        "runtime": {"platform": platform.platform(), "cpu_model": cpu_model(),
                    "python": platform.python_version(), "numpy": np.__version__,
                    "flip_evaluator": importlib.metadata.version("flip-evaluator"),
                    "scikit_image": importlib.metadata.version("scikit-image"),
                    "trimesh": importlib.metadata.version("trimesh"),
                    "node": subprocess.check_output(["node", "--version"], text=True).strip(),
                    "node_executable_sha256": digest(windows_node),
                    "codec_process": "Windows Node.js invoked from WSL2 through local interop",
                    "peak_memory_measured": False},
        "versions": {"draco": json.loads((ROOT / "third_party/draco/javascript/npm/draco3d/package.json").read_text())["version"],
                     "meshoptimizer": json.loads((ROOT / "third_party/meshoptimizer/js/package.json").read_text())["version"]},
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                    cwd=ROOT, text=True).strip(),
        "hashes": {str(path.relative_to(ROOT).as_posix()): digest(path) for path in (
            Path(__file__).resolve(), ROOT / "tools/mmtrain/geometry_codec_baseline.cjs",
            ROOT / "tools/mmtrain/meshopt_simplify.cjs",
            ROOT / "tools/mmtrain/cluster_decoder_quality.py",
            ROOT / "tools/mmtrain/compare_qem_meshopt_validation_70pct.py",
            ROOT / "tools/mmtrain/bench_geometry_codecs.py",
            ROOT / "tools/mmtrain/cluster_decoder_pilot.py",
            ROOT / "tools/mmtrain/cluster_decoder.py",
            ROOT / "tools/mmtrain/make_refinement_pairs.py",
            ROOT / "tools/mmtrain/wsl_node_bridge.sh",
            ROOT / "third_party/draco/javascript/npm/draco3d/draco_encoder.wasm",
            ROOT / "third_party/draco/javascript/npm/draco3d/draco_decoder.wasm",
            ROOT / "third_party/meshoptimizer/js/meshopt_encoder.js",
            ROOT / "third_party/meshoptimizer/js/meshopt_decoder.js",
            ROOT / "third_party/meshoptimizer/js/meshopt_simplifier.js")},
        "meshes": {
            "source": mesh_record(*source),
            "meshopt_exact_50": {**mesh_record(*meshopt_geometry),
                                 "boundary_exactly_matches_source": meshopt_boundary_equal,
                                 "simplifier_receipt": simplified_receipt},
            "manymesh_exact_50": {**mesh_record(*candidate),
                                  "boundary_exactly_matches_source": candidate_boundary_equal,
                                  "selected_ply_sha256": digest(candidate_path),
                                  "lod_graph_sha256": page["graph_json_sha256"],
                                  "mmb_sha256": page["mmb_sha256"]},
        },
        "page_accounting": page,
        "raw_geometry_quality": raw_scores,
        "codec_results": codec_rows,
        "decision": {
            "candidate_bytes": candidate_bytes, "candidate_mean_flip": candidate_flip,
            "eligible_static_controls_within_flip_tolerance": len(eligible),
            "best_static_control": (None if best_static is None else {
                "input": best_static["input"], "codec": best_static["codec"],
                "bits": best_static["bits"], "bytes": best_static["complete_geometry_bytes"],
                "mean_flip": best_static["mean"]["flip"]}),
            "byte_savings_vs_best_quality_matched_static": savings,
            "same_face_count_pareto_dominators": [{
                "input": row["input"], "codec": row["codec"], "bits": row["bits"],
                "faces": row["decoded_faces"], "bytes": row["complete_geometry_bytes"],
                "mean_flip": row["mean"]["flip"], "mean_psnr_db": row["mean"]["psnr_db"],
                "decode_median_ms": row["median_decode_ms"]} for row in dominators],
            "strongest_same_face_dominator": (None if strongest_dominator is None else {
                "input": strongest_dominator["input"],
                "codec": strongest_dominator["codec"], "bits": strongest_dominator["bits"],
                "faces": strongest_dominator["decoded_faces"],
                "bytes": strongest_dominator["complete_geometry_bytes"],
                "mean_flip": strongest_dominator["mean"]["flip"],
                "mean_psnr_db": strongest_dominator["mean"]["psnr_db"],
                "decode_median_ms": strongest_dominator["median_decode_ms"],
                "candidate_bytes_ratio": candidate_bytes /
                    strongest_dominator["complete_geometry_bytes"]}),
            "pass": bool(best_static is not None and savings is not None and savings >= 0.10
                         and candidate_boundary_equal and meshopt_boundary_equal),
            "dominated": bool(strongest_dominator is not None),
            "interpretation": ("same-face static control dominates this raw-page layout; close this representation only"
                               if strongest_dominator is not None else
                               "pilot filter only; no same-face Pareto dominator was found"),
        },
    }
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "candidate_bytes": candidate_bytes,
                      "candidate_flip": candidate_flip,
                      "eligible_static_controls": len(eligible),
                      "best_static": report["decision"]["best_static_control"],
                      "byte_savings": savings, "pass": report["decision"]["pass"]}, indent=2))


if __name__ == "__main__":
    main()

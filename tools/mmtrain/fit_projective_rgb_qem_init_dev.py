import argparse
from pathlib import Path
import hashlib
import importlib.metadata
import platform
import resource
import json
import sys
import tempfile
import time

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/mmgeo'))
sys.path.insert(0, str(ROOT / 'tools/mmtrain'))
from fit_projective_rgb_cpu import fit, score, camera_sets, MAX_DISPLACEMENT, ITERATIONS, TRAIN_SPP, SCORE_SPP
from preflight_appearance_meshes import audit, boundary, digest
from cluster_decoder_surface_quality import surface_metrics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifact-root', type=Path, required=True, help='Directory containing the projective-rgb-cpu-* CI artifact directories')
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args()
BASE = args.artifact_root.resolve()
OUT = args.output_dir.resolve()
OUT.mkdir(parents=True, exist_ok=True)
ASSETS = ['projective-rgb-cpu-GlassHurricaneCandleHolder',
          'projective-rgb-cpu-MaterialsVariantsShoe']


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def run_one(name):
    asset_dir = BASE / name
    result_path = asset_dir / 'result.json'
    geom_path = asset_dir / 'result.geometry.npz'
    qem_receipt_path = asset_dir / 'qem-control.json'
    qem_path = asset_dir / 'qem-score/qem.ply'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    qem_receipt = json.loads(qem_receipt_path.read_text(encoding='utf-8'))
    if digest(asset_dir / 'geometry.obj') != result['source_sha256']:
        raise ValueError(f'{name}: source OBJ hash differs from the fit receipt')
    if sha(result_path) != qem_receipt['fit_result_sha256']:
        raise ValueError(f'{name}: fit result hash differs from the QEM receipt')
    if sha(geom_path) != qem_receipt['fit_geometry_sha256']:
        raise ValueError(f'{name}: geometry archive hash differs from the QEM receipt')
    with np.load(geom_path, allow_pickle=False) as data:
        source = (data['source_positions'], data['source_faces'])
        meshoptimizer = (data['meshoptimizer_positions'], data['meshoptimizer_faces'])
        meshoptimizer_fitted = (data['fitted_positions'], data['fitted_faces'])
    qem_tri = trimesh.load_mesh(qem_path, process=False)
    initial = np.asarray(qem_tri.vertices, dtype=np.float64)
    faces = np.asarray(qem_tri.faces, dtype=np.int64)
    if len(faces) != result['target_faces']:
        raise ValueError(f'{name}: QEM face count mismatch: {len(faces)}')
    source_boundary = boundary(*source)
    initial_audit = audit(source_boundary, initial, faces)
    if not initial_audit['boundary_preserved'] or initial_audit['faces'] != len(faces):
        raise ValueError(f'{name}: QEM initializer ineligible: {initial_audit}')

    import drjit as dr
    import mitsuba as mi
    mi.set_variant('llvm_ad_rgb')
    dr.set_thread_count(2)
    train_views, heldout_views = camera_sets()
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='mm-qem-rgb-dev-') as temporary:
        fitted, history = fit(mi, dr, source, initial, faces, train_views, Path(temporary))
        fit_seconds = time.perf_counter() - start
        fit_audit = audit(source_boundary, fitted, faces)
        if not fit_audit['boundary_preserved'] or fitted.shape != initial.shape:
            raise ValueError(f'{name}: fitted mesh ineligible: {fit_audit}')
        if not np.array_equal(faces, np.asarray(qem_tri.faces, dtype=np.int64)):
            raise ValueError(f'{name}: fitted topology differs from QEM topology')
        scored = score(mi, {'source': source, 'qem': (initial, faces),
                            'qem_fitted': (fitted, faces),
                            'meshoptimizer': meshoptimizer,
                            'meshoptimizer_fitted': meshoptimizer_fitted},
                      heldout_views, OUT / name / 'score')
    fit_means = scored['means']['qem_fitted']
    accepted = sum(row['halvings'] is not None for row in history)
    deltas = {}
    gates = {}
    for baseline in ('qem', 'meshoptimizer_fitted'):
        base = scored['means'][baseline]
        delta = {
            'psnr_db': fit_means['pooled_psnr_db'] - base['pooled_psnr_db'],
            'ssim': fit_means['mean_ssim'] - base['mean_ssim'],
            'mean_flip': fit_means['mean_flip'] - base['mean_flip'],
        }
        deltas[baseline] = delta
        gates[baseline] = {
            'flip_improves': delta['mean_flip'] < 0,
            'psnr_within_0_1_db': delta['psnr_db'] >= -0.1,
            'ssim_within_0_001': delta['ssim'] >= -0.001,
        }
    asset_pass = (accepted > 0 and all(all(gate.values()) for gate in gates.values()))
    geometry = OUT / name / 'result.geometry.npz'
    geometry.parent.mkdir(parents=True, exist_ok=True)
    with geometry.open('wb') as stream:
        np.savez_compressed(stream, source_positions=source[0], source_faces=source[1],
                            qem_positions=initial, qem_faces=faces,
                            fitted_positions=fitted, fitted_faces=faces)
    qem_expected = qem_receipt['heldout']['metrics']['means']['qem']
    result_out = {
        'asset': name.removeprefix('projective-rgb-cpu-'),
        'scope': 'two reused development assets; not an asset-held-out test',
        'source_sha256': result['source_sha256'],
        'input_qem_ply_sha256': sha(qem_path),
        'fit_script_sha256': digest(ROOT / 'tools/mmtrain/fit_projective_rgb_cpu.py'),
        'runner_sha256': sha(Path(__file__)),
        'source_faces': result['source_faces'], 'target_faces': len(faces),
        'qem_audit': initial_audit, 'fitted_audit': fit_audit,
        'optimizer': {'iterations_max': ITERATIONS, 'accepted_steps': accepted,
                      'train_spp': TRAIN_SPP, 'heldout_spp': SCORE_SPP,
                      'max_displacement': MAX_DISPLACEMENT,
                      'wall_seconds': fit_seconds, 'history': history},
        'means': scored['means'],
        'previous_ci_qem_means': qem_expected,
        'qem_reproduction_delta': {
            key: float(scored['means']['qem'][key] - qem_expected[key])
            for key in ('pooled_psnr_db', 'mean_ssim', 'mean_flip')},
        'qem_fitted_minus_qem': deltas['qem'],
        'qem_fitted_minus_meshoptimizer_fitted': deltas['meshoptimizer_fitted'],
        'gate': {'accepted_step': accepted > 0, 'comparisons': gates,
                 'asset_pass': asset_pass},
        'asset_pass': asset_pass,
        'views': scored['views'],
        'geometry_sha256': sha(geometry), 'geometry_bytes': geometry.stat().st_size,
        'limitations': ['Development-only reused asset; no cross-asset inference.',
                        'CPU Mitsuba render; no GPU, mobile, MSAA, SMAA, or upscaler result.']
    }
    path = OUT / name / 'result.json'
    path.write_text(json.dumps(result_out, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'asset': result_out['asset'], 'target_faces': len(faces),
                      'qem_fitted_minus_qem': deltas['qem'],
                      'qem_fitted_minus_meshoptimizer_fitted': deltas['meshoptimizer_fitted'],
                      'accepted_steps': accepted,
                      'asset_pass': result_out['asset_pass'], 'wall_seconds': fit_seconds},
                     separators=(',', ':')), flush=True)
    return result_out


all_results = [run_one(name) for name in ASSETS]
passed = all(item['asset_pass'] for item in all_results)
summary = {
    'date': '2026-11-27',
    'protocol': 'tools/mmtrain/PROJECTIVE_RGB_QEM_INITIALIZED_FIT_DEV_PROTOCOL_20261127.md',
    'workflow_run': 45852622096,
    'runner_sha256': sha(Path(__file__)),
    'python': sys.version.split()[0],
    'platform': platform.platform(),
    'packages': {name: importlib.metadata.version(name) for name in (
        'mitsuba', 'drjit', 'numpy', 'scipy', 'scikit-image', 'flip-evaluator', 'trimesh')},
    'assets': [item['asset'] for item in all_results],
    'decision': ('Passes two-model development screen only; freeze independent confirmation before any generalization claim.'
                 if passed else 'Fails the frozen two-model development gate; do not score the reserved 30-model pool.'),
    'all_assets_pass': passed,
    'peak_rss_bytes': int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
    'limitations': ['Two reused development assets only.',
                    'A pass is feasibility evidence, not novelty or generalization.',
                    'No production runtime or device measurement.']
}
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, separators=(',', ':')), flush=True)

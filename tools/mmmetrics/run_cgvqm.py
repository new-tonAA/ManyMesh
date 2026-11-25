#!/usr/bin/env python3
"""Run the upstream CGVQM metric on a paired video sequence using OpenCV decode."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import types

import cv2
import numpy as np


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_video_cv2(path, output_format="TCHW", pts_unit="sec"):
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV FFmpeg could not open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames = []
    try:
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()
    if not frames:
        raise ValueError(f"Video has no decodable frames: {path}")
    import torch

    video = torch.from_numpy(np.stack(frames))
    if output_format == "TCHW":
        video = video.permute(0, 3, 1, 2).contiguous()
    elif output_format != "THWC":
        raise ValueError(f"Unsupported output format: {output_format}")
    return video, torch.empty(0), {"video_fps": fps}


def video_metadata(path):
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV FFmpeg could not open video: {path}")
    try:
        return {
            "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "frameCount": int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
            "fps": float(capture.get(cv2.CAP_PROP_FPS)),
            "backend": capture.getBackendName(),
        }
    finally:
        capture.release()


def load_upstream(repo):
    repo = repo.resolve()
    if not (repo / "cgvqm.py").is_file() or not (repo / "utils" / "resnet18.py").is_file():
        raise FileNotFoundError("--cgvqm-root must point to the IntelLabs/cgvqm checkout")

    package = types.ModuleType("utils")
    package.__path__ = [str(repo / "utils")]
    package.__package__ = "utils"
    sys.modules["utils"] = package
    # The upstream reader is patched below. This placeholder avoids requiring PyAV just to import it.
    av_stub = types.ModuleType("av")
    av_stub.logging = types.SimpleNamespace(ERROR=0, set_level=lambda level: None)
    frame_type = type("VideoFrame", (), {"pict_type": None})
    av_stub.video = types.SimpleNamespace(
        frame=types.SimpleNamespace(VideoFrame=frame_type))
    av_stub.FFmpegError = Exception
    sys.modules["av"] = av_stub
    sys.path.insert(0, str(repo))

    spec = importlib.util.spec_from_file_location("cgvqm_upstream", repo / "cgvqm.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from utils import utils as upstream_utils

    upstream_utils.read_video = read_video_cv2
    return module, upstream_utils


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgvqm-root", type=Path, required=True)
    parser.add_argument("--distorted", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", choices=("CGVQM-2", "CGVQM-5"), default="CGVQM-5")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--patch-pool", choices=("max", "mean"), default="mean")
    parser.add_argument("--patch-scale", type=int, default=4)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--torch-home", type=Path,
                        default=Path("out/deps/torch_home"))
    args = parser.parse_args()

    distorted = args.distorted.resolve()
    reference = args.reference.resolve()
    for path in (distorted, reference):
        if not path.is_file():
            raise FileNotFoundError(path)
    distorted_meta = video_metadata(distorted)
    reference_meta = video_metadata(reference)
    if distorted_meta != reference_meta:
        raise ValueError(f"Video streams must match exactly: {distorted_meta} != {reference_meta}")

    torch_home = args.torch_home.resolve()
    torch_home.mkdir(parents=True, exist_ok=True)
    os.environ["TORCH_HOME"] = str(torch_home)
    import torch

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    if args.cpu_threads < 1:
        raise ValueError("--cpu-threads must be positive")
    if args.device == "cpu":
        torch.set_num_threads(args.cpu_threads)
        torch.set_num_interop_threads(1)
    metric, upstream_utils = load_upstream(args.cgvqm_root)
    model_type = (metric.CGVQM_TYPE.CGVQM_2 if args.model == "CGVQM-2"
                  else metric.CGVQM_TYPE.CGVQM_5)
    start = time.perf_counter()
    quality, _ = metric.run_cgvqm(
        str(distorted), str(reference), cgvqm_type=model_type, device=args.device,
        patch_pool=args.patch_pool, patch_scale=args.patch_scale)
    elapsed_seconds = time.perf_counter() - start

    cgvqm_root = args.cgvqm_root.resolve()
    backbone = torch_home / "hub" / "checkpoints" / "r3d_18-b3b3357e.pth"
    calibration = cgvqm_root / "weights" / f"cgvqm-{args.model[-1]}.pickle"
    report = {
        "metric": args.model,
        "score": float(quality.item()),
        "scoreDirection": "higher_is_better",
        "patchPool": args.patch_pool,
        "patchScale": args.patch_scale,
        "device": args.device,
        "cpuThreads": args.cpu_threads if args.device == "cpu" else None,
        "elapsedSeconds": elapsed_seconds,
        "upstreamRepository": "https://github.com/IntelLabs/cgvqm",
        "upstreamCommit": __import__("subprocess").check_output(
            ["git", "-C", str(cgvqm_root), "rev-parse", "HEAD"], text=True).strip(),
        "decoder": "OpenCV FFmpeg backend; RGB24 conversion; upstream PyAV reader replaced",
        "opencvVersion": cv2.__version__,
        "distorted": {"path": str(distorted), "sha256": sha256(distorted),
                      **distorted_meta},
        "reference": {"path": str(reference), "sha256": sha256(reference),
                      **reference_meta},
        "calibrationWeightsSha256": sha256(calibration),
        "r3d18WeightsSha256": sha256(backbone),
        "torchVersion": torch.__version__,
        "torchvisionVersion": __import__("torchvision").__version__,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

"""Time the compact 2x CPU upsampler against bicubic on a saved mesh render."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F

from train import TinyUpsample


def measure(function, repeats, warmup):
    for _ in range(warmup):
        function()
    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        values.append((time.perf_counter() - start) * 1000)
    return {"medianMs": float(np.median(values)),
            "p95Ms": float(np.percentile(values, 95)),
            "samples": len(values)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=8)
    args = parser.parse_args()
    if args.threads < 1 or args.repeats < 1 or args.warmup < 0:
        parser.error("threads and repeats must be positive; warmup cannot be negative")
    torch.set_num_threads(args.threads)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model = TinyUpsample(3, 2, 32)
    model.load_state_dict(checkpoint)
    model.eval()
    image = Image.open(args.input).convert("RGB")
    rows = []
    for width, height in ((96, 96), (320, 180)):
        resized = image.resize((width, height), Image.Resampling.BICUBIC)
        array = np.asarray(resized).astype(np.float32) / 255.0
        tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)

        def learned():
            with torch.inference_mode():
                return model(tensor)

        def bicubic():
            with torch.inference_mode():
                return F.interpolate(tensor, scale_factor=2, mode="bicubic", align_corners=False)

        rows.append({"input": [width, height], "output": [2 * width, 2 * height],
                     "tinyUpsample": measure(learned, args.repeats, args.warmup),
                     "torchBicubic": measure(bicubic, args.repeats, args.warmup)})
    result = {"model": "TinyUpsample", "parameters": sum(p.numel() for p in model.parameters()),
              "checkpointSha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
              "inputSha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
              "torch": torch.__version__, "python": platform.python_version(),
              "device": "CPU", "threads": args.threads, "warmup": args.warmup,
              "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

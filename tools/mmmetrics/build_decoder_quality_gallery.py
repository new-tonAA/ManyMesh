"""Compose measured view-zero validation images and official FLIP error maps."""

import argparse
import json
from pathlib import Path

import flip_evaluator
import numpy as np
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    size = report["size"]
    panels = []
    for row in report["records"]:
        if row["split"] != "validation" or "fixed" not in row.get("variants", {}):
            continue
        folder = args.report.parent / f"validation-{row['file_id']}"
        images = [np.asarray(Image.open(folder/f"{name}-v00.png").convert("RGB"))
                  for name in ("reference", "base", "fixed")]
        error_maps = []
        for name, candidate in zip(("base", "fixed"), images[1:]):
            color, mean, _ = flip_evaluator.evaluate(images[0].astype(np.float32)/255,
                                                     candidate.astype(np.float32)/255, "LDR",
                                                     parameters={"ppd": report["metrics"]["flip_ppd"]})
            if abs(mean-row["variants"][name]["per_view"][0]["flip"]) > 1e-6:
                raise ValueError("Saved image does not reproduce recorded FLIP")
            error_maps.append(np.clip(np.rint(color*255), 0, 255).astype(np.uint8))
        panel = Image.new("RGB", (5*size, size+48), "#20252b")
        draw = ImageDraw.Draw(panel)
        for i, (image, label) in enumerate(zip(images+error_maps,
                ("Reference", "QEM", "Cluster decoder", "FLIP: reference/QEM", "FLIP: reference/decoder"))):
            draw.text((i*size+5, 4), f"Validation {row['file_id']} | v00", fill="white")
            draw.text((i*size+5, 20), label, fill="white")
            panel.paste(Image.fromarray(image), (i*size, 48))
        panels.append(panel)
    if not panels:
        raise ValueError("No paired validation outputs")
    sheet = Image.new("RGB", (5*size, sum(p.height for p in panels)))
    for i, panel in enumerate(panels):
        sheet.paste(panel, (0, i*(size+48)))
    sheet.save(args.out)


if __name__ == "__main__":
    main()

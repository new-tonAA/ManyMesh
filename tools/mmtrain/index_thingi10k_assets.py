"""Create the source manifest expected by make_refinement_pairs from a Thingi10K download."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("download_manifest", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.download_manifest.resolve()
    root = manifest_path.parent
    download = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = []
    for row in download["files"]:
        path = (root / row["path"]).resolve()
        if not path.is_file() or path.stat().st_size != row["bytes"]:
            raise ValueError(f"Downloaded mesh missing or size changed: {path}")
        sources.append({
            "name": f"thing_{row['thing_id']}_{row['file_id']}",
            "mesh": str(path),
            "buffers": {path.name: row["sha256"]},
            "split": row["split"],
            "faces": row["faces"],
            "license": row["license"],
            "thingId": row["thing_id"],
            "fileId": row["file_id"],
        })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    print(f"assets={len(sources)} triangles={sum(x['faces'] for x in sources)} output={args.out}")


if __name__ == "__main__":
    main()

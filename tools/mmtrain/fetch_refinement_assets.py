"""Fetch geometry buffers and credits for the public raster refinement pilot."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote
from urllib.request import urlopen


REVISION = "f0920f5b32d172a30efe3f9257e965918831e6ea"
BASE = f"https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/{REVISION}/Models"
ASSETS = {
    "AntiqueCamera": "CC0-1.0",
    "Avocado": "CC0-1.0",
    "BarramundiFish": "CC0-1.0",
    "CesiumMilkTruck": "CC-BY-4.0",
    "Lantern": "CC0-1.0",
    "SheenChair": "CC0-1.0",
    "ToyCar": "CC0-1.0",
    "WaterBottle": "CC0-1.0",
}
MAX_BYTES = 10 * 1024 * 1024


def fetch(url, path, maximum):
    with urlopen(url, timeout=20) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"Download exceeds {maximum} bytes: {url}")
    path.write_bytes(data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sources = []
    for name, license_id in ASSETS.items():
        directory = args.out / name
        directory.mkdir(parents=True, exist_ok=True)
        source = f"{BASE}/{name}"
        license_text = fetch(f"{source}/LICENSE.md", directory / "LICENSE.md", 32_768).decode()
        if license_id not in license_text.split("* This file")[0]:
            raise ValueError(f"Missing expected asset license: {name}")
        fetch(f"{source}/README.md", directory / "README.md", 100_000)
        destination = directory / f"{name}.gltf"
        document = json.loads(fetch(f"{source}/glTF/{destination.name}", destination, 200_000))
        buffers = {}
        for buffer in document["buffers"]:
            uri = buffer["uri"]
            filename = unquote(uri)
            if Path(filename).name != filename or ":" in filename or "?" in filename:
                raise ValueError(f"Expected a local geometry buffer file: {name}: {uri}")
            data = fetch(f"{source}/glTF/{uri}", directory / filename, MAX_BYTES)
            if len(data) != buffer["byteLength"]:
                raise ValueError(f"Buffer length mismatch: {name}: {uri}")
            buffers[filename] = hashlib.sha256(data).hexdigest()
        sources.append({"name": name, "license": license_id, "source": source,
                        "mesh": str(destination.relative_to(args.out)), "buffers": buffers})
        print(f"{name}: {license_id}, {sum(b['byteLength'] for b in document['buffers']):,} bytes",
              flush=True)
    (args.out / "sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

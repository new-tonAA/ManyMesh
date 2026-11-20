"""Download a license-filtered Thingi10K manifest with strict byte limits."""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--split", choices=("train", "validation", "test", "all"), default="train")
    parser.add_argument("--max-file-mib", type=int, default=24)
    parser.add_argument("--max-total-mib", type=int, default=160)
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    items = [item for item in manifest["items"]
             if args.split == "all" or item["split"] == args.split]
    args.output.mkdir(parents=True, exist_ok=True)
    max_file = args.max_file_mib * 1024 * 1024
    max_total = args.max_total_mib * 1024 * 1024
    total = 0
    results = []

    for item in items:
        name = f"{item['file_id']}{item['extension']}"
        path = args.output / name
        if path.exists():
            size = path.stat().st_size
            if size > max_file:
                raise RuntimeError(f"existing file exceeds limit: {path}")
            if total + size > max_total:
                raise RuntimeError(f"existing files exceed {args.max_total_mib} MiB total cap")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            total += size
            results.append({**item, "path": name, "bytes": size, "sha256": digest,
                            "status": "existing"})
            continue

        request = urllib.request.Request(item["mirror_url"], headers={"User-Agent": "ManyMesh-research/1.0"})
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            length = response.headers.get("Content-Length")
            expected = int(length) if length is not None else None
            if expected is not None and expected > max_file:
                raise RuntimeError(f"file exceeds {args.max_file_mib} MiB cap: {name} ({expected} bytes)")
            if expected is not None and total + expected > max_total:
                raise RuntimeError(f"download would exceed {args.max_total_mib} MiB total cap")
            digest = hashlib.sha256()
            size = 0
            with path.open("wb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_file or total + size > max_total:
                        raise RuntimeError(f"stream exceeded configured byte cap: {name}")
                    digest.update(chunk)
                    stream.write(chunk)
            if expected is not None and size != expected:
                path.unlink(missing_ok=True)
                raise RuntimeError(f"incomplete download for {name}: {size} != {expected}")

        total += size
        results.append({**item, "path": name, "bytes": size, "sha256": digest.hexdigest(),
                        "status": "downloaded"})
        print(f"{item['split']} {name} {size} bytes sha256={digest.hexdigest()}", flush=True)

    report = {"manifest": str(args.manifest), "split": args.split, "files": results,
              "totalBytes": total, "maxFileBytes": max_file, "maxTotalBytes": max_total}
    report_path = args.output / "download_manifest.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"downloaded={sum(x['status'] == 'downloaded' for x in results)} "
          f"total={total} bytes report={report_path}")


if __name__ == "__main__":
    main()

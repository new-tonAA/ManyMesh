"""Fetch and topology-screen a frozen Poly Haven geometry candidate batch."""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


USER_AGENT = "ManyMesh-Research/1.0"
API_ROOT = "https://api.polyhaven.com"
DOWNLOAD_HOST = "dl.polyhaven.org"
TERMS_URL = "https://github.com/Poly-Haven/Public-API/blob/master/ToS.md"
REQUEST_DELAY_SECONDS = 0.15


def sha(data):
    return hashlib.sha256(data).hexdigest()


def md5(data):
    return hashlib.md5(data).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def get_bytes(url, counters, expected_size=None, expected_md5=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
    for attempt in range(6):
        time.sleep(REQUEST_DELAY_SECONDS)
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = response.read()
                counters["requests"] += 1
                if expected_size is not None and len(payload) != expected_size:
                    raise ValueError(f"Size mismatch for {url}: {len(payload)} != {expected_size}")
                if expected_md5 is not None and md5(payload) != expected_md5:
                    raise ValueError(f"Published MD5 mismatch for {url}")
                return payload
        except urllib.error.HTTPError as error:
            counters["requests"] += 1
            if error.code == 429 or 500 <= error.code < 600:
                counters["retries"] += 1
                retry_after = error.headers.get("Retry-After")
                delay = min(120.0, float(retry_after)) if retry_after and retry_after.isdigit() else 2.0 ** attempt
                time.sleep(delay)
                continue
            raise
        except (TimeoutError, urllib.error.URLError):
            counters["retries"] += 1
            if attempt == 5:
                raise
            time.sleep(2.0 ** attempt)
    raise RuntimeError(f"Retry limit reached for {url}")


def walk_file_records(value):
    if isinstance(value, dict):
        if isinstance(value.get("url"), str) and "md5" in value:
            yield value
        for child in value.values():
            yield from walk_file_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_file_records(child)


def acquire_candidate(candidate, destination, counters, extract, write_obj, audit):
    slug = candidate["asset"]
    api_url = f"{API_ROOT}/files/{urllib.parse.quote(slug, safe='')}"
    files_bytes = get_bytes(api_url, counters)
    files = json.loads(files_bytes)
    gltf_record = files.get("gltf", {}).get("1k", {}).get("gltf")
    if not gltf_record:
        raise ValueError("The asset has no 1k glTF source")
    gltf_url = gltf_record["url"]
    gltf_bytes = get_bytes(gltf_url, counters, gltf_record.get("size"), gltf_record["md5"])
    document = json.loads(gltf_bytes)
    if document.get("asset", {}).get("version") != "2.0":
        raise ValueError("Expected a glTF 2.0 document")
    buffers = document.get("buffers", [])
    if len(buffers) != 1 or not isinstance(buffers[0].get("uri"), str):
        raise ValueError("Expected one external glTF geometry buffer")
    buffer_uri = buffers[0]["uri"]
    include_files = gltf_record.get("include", {})
    bin_record = include_files.get(buffer_uri)
    if not bin_record:
        matches = [record for record in include_files.values()
                   if Path(urllib.parse.urlparse(record.get("url", "")).path).name
                   == Path(urllib.parse.urlparse(buffer_uri).path).name]
        if len(matches) == 1:
            bin_record = matches[0]
    if not bin_record:
        raise ValueError("The 1k glTF API record does not checksum its declared geometry buffer")
    buffer_url = bin_record["url"]
    parsed_url = urllib.parse.urlparse(buffer_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != DOWNLOAD_HOST:
        raise ValueError("The glTF buffer URL is outside the pinned Poly Haven download host")
    binary = get_bytes(buffer_url, counters, bin_record.get("size"), bin_record["md5"])
    if len(binary) < buffers[0]["byteLength"]:
        raise ValueError("The geometry buffer is shorter than its glTF declaration")

    asset_dir = destination / slug
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "source.gltf").write_bytes(gltf_bytes)
    (asset_dir / "source.bin").write_bytes(binary)
    files_path = asset_dir / "api-files.json"
    write_json(files_path, files)

    extraction = {"status": "pass"}
    try:
        positions, triangles, scene = extract(document, binary)
        obj_path = asset_dir / "geometry.obj"
        write_obj(obj_path, positions, triangles)
        topology = audit(obj_path)
        extraction.update({"vertices": int(len(positions)), "triangles": int(len(triangles)),
                           "mesh_instances": scene["mesh_instances"],
                           "triangle_primitives": scene["triangle_primitives"],
                           "animation_count_ignored": scene["animation_count_ignored"],
                           "obj_sha256": sha(obj_path.read_bytes()),
                           "topology": topology})
        extraction["topology_status"] = topology["topology_status"]
    except Exception as error:
        extraction = {"status": "fail", "error": f"{type(error).__name__}: {error}"}

    return {
        **candidate,
        "asset_license": "CC0 per current Poly Haven policy; preserved as candidate source, with creator credit recorded",
        "catalog_api_record": {
            "url": api_url,
            "files_json_sha256": sha(files_bytes),
            "files_hash_matches_catalog": files.get("files_hash") == candidate.get("catalog_files_hash"),
            "authors": candidate.get("authors", {}),
        },
        "source_files": {
            "gltf": {"url": gltf_url, "api_md5": gltf_record["md5"],
                     "bytes": len(gltf_bytes), "sha256": sha(gltf_bytes)},
            "bin": {"url": buffer_url, "api_md5": bin_record["md5"],
                    "bytes": len(binary), "sha256": sha(binary),
                    "declared_byte_length": buffers[0]["byteLength"]},
        },
        "local_asset_directory": str(asset_dir),
        "extraction": extraction,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    tool_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(tool_dir))
    from audit_static_obj_topology import audit
    from extract_static_gltf_geometry import extract, write_obj

    selection_bytes = args.selection.read_bytes()
    selection = json.loads(selection_bytes)
    candidates = [candidate for group in selection["selection"]["classes"]
                  for candidate in group["selected"]]
    if len(candidates) != selection["selected_count"]:
        raise ValueError("The frozen selection count does not match its candidate rows")

    script_hashes = {name: sha((tool_dir / name).read_bytes()) for name in (
        Path(__file__).name, "select_polyhaven_expansion.py",
        "extract_static_gltf_geometry.py", "audit_static_obj_topology.py")}
    report = {
        "schema": 1,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Poly Haven Public API",
        "terms_url": TERMS_URL,
        "user_agent": USER_AGENT,
        "selection_sha256": sha(selection_bytes),
        "catalog_sha256": selection["catalog_sha256"],
        "script_sha256": script_hashes,
        "quality_scored": False,
        "image_or_render_data_used": False,
        "request_counters": {"requests": 0, "retries": 0},
        "assets": [],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(candidates, 1):
        try:
            row = acquire_candidate(candidate, args.out_dir, report["request_counters"],
                                    extract, write_obj, audit)
        except Exception as error:
            row = {**candidate, "acquisition_status": "fail",
                   "acquisition_error": f"{type(error).__name__}: {error}"}
        else:
            row["acquisition_status"] = "pass"
        report["assets"].append(row)
        write_json(args.report, report)
        extraction = row.get("extraction", {})
        print(index, row["asset"], row["acquisition_status"],
              extraction.get("topology_status", extraction.get("error", "")), flush=True)
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(args.report, report)


if __name__ == "__main__":
    main()

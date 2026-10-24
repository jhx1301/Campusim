"""Archive explicitly listed public sources; keep HTTP failures in the manifest."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent


def fetch(source):
    path = ROOT / "raw" / source["file"]
    timestamp = datetime.now(timezone.utc).isoformat()
    result = {**source, "retrieved_at": timestamp}
    request = urllib.request.Request(source["url"])
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            body = response.read()
            path.write_bytes(body)
            result.update(status="downloaded", http_status=response.status, final_url=response.url,
                          content_type=response.headers.get("Content-Type"), bytes=len(body),
                          sha256=hashlib.sha256(body).hexdigest())
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        result.update(status="failed", error=str(error), http_status=getattr(error, "code", None))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", nargs="*", help="Fetch only these source IDs; default fetches missing sources")
    args = parser.parse_args()
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    manifest_path = ROOT / "download_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    done = {item["id"] for item in manifest if item["status"] == "downloaded"}
    selected = [s for s in sources if (s["id"] in args.ids if args.ids else s["id"] not in done)]
    (ROOT / "raw").mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(fetch, selected):
            manifest.append(result)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            print(result["id"], result["status"], result.get("http_status"), result.get("bytes", result.get("error")), flush=True)


if __name__ == "__main__":
    main()

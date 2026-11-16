"""Collect unmodified Qt 5.15.2 notices/attributions from official source mirrors."""
import concurrent.futures
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1] / "docs" / "licenses" / "qt5-5.15.2"


def get(url):
    with urlopen(Request(url, headers={"User-Agent": "ATLAS-Watchdog-notice-collection"}), timeout=45) as response:
        return response.read()


def collect(repository):
    tree = json.loads(get(f"https://api.github.com/repos/qt/{repository}/git/trees/v5.15.2?recursive=1"))
    assert not tree.get("truncated")
    paths = set()
    for item in tree["tree"]:
        path = item["path"]
        if item["type"] != "blob":
            continue
        if path.endswith("qt_attribution.json") or (re.match(r"^(LICENSE|LICENCE|COPYING|COPYRIGHT|NOTICE)", PurePosixPath(path).name, re.I)
                                                  and ("3rdparty/" in path or "/" not in path)):
            paths.add(path)
    fetched = {}
    def fetch(path):
        url = f"https://raw.githubusercontent.com/qt/{repository}/v5.15.2/{path}"
        return path, get(url), url
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for path, data, url in pool.map(fetch, sorted(paths)):
            fetched[path] = (data, url)
    # Also preserve files explicitly referenced by attribution metadata.
    extras = set()
    for path, (data, _) in list(fetched.items()):
        if not path.endswith("qt_attribution.json"):
            continue
        metadata = json.loads(data, strict=False)  # Some upstream files contain literal tabs.
        for record in metadata if isinstance(metadata, list) else [metadata]:
            for value in [record.get("LicenseFile", "")]:
                if value:
                    import posixpath
                    target = posixpath.normpath(str(PurePosixPath(path).parent / value))
                    if not target.startswith("../") and target not in fetched:
                        extras.add(target)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for path, data, url in pool.map(fetch, sorted(extras)):
            fetched[path] = (data, url)
    destination = ROOT / repository
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for path, (data, url) in sorted(fetched.items()):
        filename = path.replace("/", "__")
        if not filename.endswith(".json"):
            filename += ".txt"
        (destination / filename).write_bytes(data)
        records.append(dict(original_path=path, local_file=filename, url=url, sha256=hashlib.sha256(data).hexdigest()))
    (destination / "MANIFEST.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"{repository}: preserved {len(records)} upstream notices/attributions")


if __name__ == "__main__":
    for repository in ("qtbase", "qtdeclarative"):
        collect(repository)

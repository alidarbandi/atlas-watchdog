"""Read PE metadata; report imports without guessing that API sets are missing."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from importlib.util import find_spec

import pefile


def inspect(folder):
    folder = Path(folder).resolve()
    records = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".exe", ".dll", ".pyd"}:
            continue
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        imports = []
        for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for item in getattr(pe, attribute, []):
                imports.append(dict(library=item.dll.decode("ascii", errors="replace"),
                                    symbols=[i.name.decode("ascii", errors="replace") if i.name else "ordinal:" + str(i.ordinal) for i in item.imports]))
        version = None
        if getattr(pe, "VS_FIXEDFILEINFO", None):
            info = pe.VS_FIXEDFILEINFO[0]
            version = ".".join(map(str, (info.FileVersionMS >> 16, info.FileVersionMS & 65535,
                                       info.FileVersionLS >> 16, info.FileVersionLS & 65535)))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record = dict(path=path.relative_to(folder).as_posix(), machine=hex(pe.FILE_HEADER.Machine),
                      file_version=version, sha256=digest, imports=imports)
        if "140" in path.name.lower():
            candidates = [("CPython distribution", Path(sys.base_prefix) / path.name),
                          ("CPython distribution", Path(sys.base_prefix) / "DLLs" / path.name)]
            for binding in ("PySide2", "shiboken2", "PySide6", "shiboken6"):
                spec = find_spec(binding)
                if spec is not None and spec.origin:
                    candidates.append((binding + " wheel", Path(spec.origin).parent / path.name))
            sources = [provider for provider, source in candidates if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == digest]
            assert sources, f"Runtime provenance not established for {path.name}; do not copy system DLLs"
            record["matching_distribution"] = sorted(set(sources))
        records.append(record)
        pe.close()
    assert records and all(item["machine"] == "0x8664" for item in records), "Non-x64 PE found"
    return dict(note="Actual binary metadata, not target-OS dependency resolution. API sets are Windows contracts.", binaries=records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(inspect(args.folder), indent=2), encoding="utf-8")

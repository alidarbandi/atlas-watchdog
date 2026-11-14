"""Sanitized, clearly marked simulated ATLAS sources, confined to a demo folder."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path


class DemoWriter:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.paths = {name: self.directory / filename for name, filename in
                      [("engine", "atlasengine.log"), ("execution", "execution_log.log")]}
        for path in self.paths.values():
            path.write_bytes(b"")
        self.paused = False
        self.index = 0
        self.pending = {}

    def _line(self, level, component, message):
        stamp = datetime.now().strftime("%d/%m/%Y\t%H:%M:%S.%f")[:-3]
        return f"{stamp}\t{level}\t{component}\t\t{message}\r\n".encode("cp1252")

    def step(self):
        if self.paused:
            return
        for source, data in list(self.pending.items()):
            with self.paths[source].open("ab") as out:
                out.write(data)
            del self.pending[source]
        records = [
            ("Info", "Imaging", "DEMO Image completed - slice_00001_z=0.0325um.tif"),
            ("Info", "Atlas 3D", f"Process is alive. ImageNo={self.index // 8 + 1}; MillZ={self.index // 8 * .0325:.4f} um"),
            ("Trace", "System", "DEMO measured 12.5 µm at 23.0°"),
            ("Error", "Imaging", "The connection or the microscope does not respond."),
            ("Log", "Atlas 3D", "DEMO diagnostic, acquisition observation only"),
            ("Error", "Imaging", "Cannot grab image since the beam is blanked."),
            ("Error", "Imaging", "Imaging beam shift X failed target: 0.8428 actual: 1.3925. Unable to recover. Stopping acquisition."),
            ("Info", "Atlas 3D", "Run Ended."),
        ]
        level, component, message = records[self.index % len(records)]
        for name, record in [("execution", self._line(level, component, message)),
                             ("engine", self._line("Log", "System", "DEMO engine temperature 23.0°" if self.index % 4 else "WMAcqError WP=8 r=False"))]:
            # Split a record, including the CRLF boundary, across separate simulator steps.
            cut = len(record) - 1 if self.index % 3 == 0 else len(record) // 2
            with self.paths[name].open("ab") as out:
                out.write(record[:cut])
            self.pending[name] = record[cut:]
        self.index += 1

    def mutate(self, action):
        for name, path in self.paths.items():
            # Never accepts arbitrary input paths; only the two files created by this writer.
            if path.parent.resolve() != self.directory:
                raise ValueError("Demo destination escaped its dedicated directory.")
            if action == "rotate":
                rotated = path.with_suffix(".log.1")
                path.replace(rotated)
                path.write_bytes(b"")
            elif action == "truncate":
                path.write_bytes(b"")
            elif action == "burst":
                with path.open("ab") as out:
                    out.write(self._line("Error", "DEMO", "DEMO burst fault: target 0.8428") * 40)
        self.pending.clear()

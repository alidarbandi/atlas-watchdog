"""ATLAS records: explicit day/month/year timestamps and literal messages."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_LEVELS = {x.casefold(): x for x in ("Trace", "Debug", "Log", "Info", "Warning", "Error", "Fatal", "Critical")}
_LEVELS["warn"] = "Warning"


def parse_line(text: str, source: str, raw_b64: str = "", diagnostic: str = "",
               source_timezone: str = "") -> dict:
    now = datetime.now().astimezone()
    result = dict(source=source, timestamp_original="", timestamp_iso="", level="Unknown",
                  component="", message=text, raw_line=text, raw_b64=raw_b64,
                  diagnostic=diagnostic, receipt_local=now.isoformat(),
                  receipt_utc=now.astimezone(timezone.utc).isoformat(), record_type="record")
    # Exact observed header only; similar text containing errors stays visible.
    # Keep any reader/decode diagnostic even on a recognized header/separator.
    if source == "engine" and text == "Application log":
        result.update(level="Info", component="Log header", record_type="header")
        return result
    if not text.strip():
        result.update(level="Not applicable", record_type="separator")
        return result
    notes = [diagnostic] if diagnostic else []
    fields = text.split("\t", 4)
    if len(fields) < 5:
        result["record_type"] = "unstructured"
        notes.append("Malformed/unstructured record; original text retained")
    else:
        date, time, level, component, message = fields
        original = f"{date} {time}"
        result.update(timestamp_original=original, level=_LEVELS.get(level.strip().casefold(), level.strip()),
                      component=component.strip(), message=message.lstrip("\t"))
        try:
            stamp = datetime.strptime(original, "%d/%m/%Y %H:%M:%S.%f")
            if source_timezone:
                stamp = stamp.replace(tzinfo=ZoneInfo(source_timezone))
            result["timestamp_iso"] = stamp.isoformat()
        except (ValueError, ZoneInfoNotFoundError):
            notes.append("Invalid timestamp or source timezone; original retained")
    result["diagnostic"] = "; ".join(notes)
    return result

"""Bounded byte tailing with an entirely serializable checkpoint.

Checkpoint stores *read cursor plus pending bytes and discard state*. The caller
must commit it transactionally with all produced events. No mutable checkpoint
input is changed. After a failed transaction, rereading the old checkpoint is safe.
Oversized records retain a bounded prefix, emit a diagnostic record immediately,
then discard through the next aligned newline. Bytes lost during rotation cannot
be recovered unless the producer supplies a separately configured convention.
"""
from __future__ import annotations

import base64
import hashlib
import uuid
from dataclasses import dataclass, field

from .file_access import SharedFile


@dataclass
class RawLine:
    offset: int
    end_offset: int
    text: str
    raw_b64: str
    diagnostic: str = ""


@dataclass
class TailBatch:
    lines: list[RawLine]
    checkpoint: dict
    bytes_read: int
    backlog: int
    diagnostics: list[str] = field(default_factory=list)
    encoding: str = ""
    reset_recovered: bool = False


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _detect(prefix: bytes, override: str):
    aliases = {"utf8": "utf-8", "utf-8-sig": "utf-8", "windows-1252": "cp1252"}
    override = aliases.get(override.lower(), override.lower())
    if override not in ("auto", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "cp1252"):
        raise ValueError("Unsupported source encoding")
    if override in ("auto", "utf-16"):
        if prefix.startswith(b"\xff\xfe"):
            return "utf-16-le", 2
        if prefix.startswith(b"\xfe\xff"):
            return "utf-16-be", 2
    if override == "utf-16":
        if not prefix or prefix in (b"\xff", b"\xfe"):
            return "auto-8bit", 0  # wait for the complete BOM to establish byte order
        raise ValueError("UTF-16 requires a byte-order mark or an explicit byte order")
    if override == "auto":
        return ("utf-8", 3) if prefix.startswith(b"\xef\xbb\xbf") else ("auto-8bit", 0)
    bom = 2 if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) else 3 if prefix.startswith(b"\xef\xbb\xbf") else 0
    return override, bom


def _partial_bom(prefix: bytes) -> bool:
    return bool(prefix) and any(len(prefix) < len(bom) and bom.startswith(prefix)
                                for bom in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf"))


def _checkpoint_pending(cp: dict, max_record_bytes: int) -> bytes:
    """Reject a malformed durable state before it can change offsets/decoder."""
    if type(cp["schema"]) is not int or cp["schema"] != 1:
        raise ValueError("Invalid checkpoint schema")
    for field in ("offset", "pending_start"):
        if type(cp[field]) is not int or cp[field] < 0:
            raise ValueError("Invalid checkpoint cursor")
    if type(cp["discard"]) is not bool:
        raise ValueError("Invalid checkpoint discard state")
    if cp["encoding"] not in {"auto-8bit", "utf-8", "utf-16-le", "utf-16-be", "cp1252"}:
        raise ValueError("Invalid checkpoint encoding")
    for field, length in (("generation", 32), ("boundary_hash", 64)):
        value = cp[field]
        if not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Invalid checkpoint identity/hash")
    if not isinstance(cp["identity"], str) or not cp["identity"] or not isinstance(cp["path"], str):
        raise ValueError("Invalid checkpoint file identity")
    if not isinstance(cp["pending"], str) or len(cp["pending"]) > ((max_record_bytes + 2) // 3) * 4:
        raise ValueError("Invalid checkpoint suffix")
    pending = base64.b64decode(cp["pending"], validate=True)
    if len(pending) > max_record_bytes or cp["pending_start"] + len(pending) != cp["offset"]:
        raise ValueError("Invalid checkpoint suffix range")
    return pending


def _newline(data: bytes, start: int, encoding: str) -> tuple[int, int]:
    marker = b"\n\x00" if encoding == "utf-16-le" else b"\x00\n" if encoding == "utf-16-be" else b"\n"
    index = data.find(marker)
    if len(marker) == 2:
        while index >= 0 and (start + index) % 2:
            index = data.find(marker, index + 1)
    return index, len(marker)


def _decode(data: bytes, encoding: str):
    if encoding == "auto-8bit":
        try:
            return data.decode("utf-8"), ""
        except UnicodeDecodeError:
            return data.decode("cp1252", errors="backslashreplace"), "Strict UTF-8 failed; CP1252 fallback (raw bytes retained)"
    try:
        return data.decode(encoding), ""
    except UnicodeDecodeError:
        return data.decode(encoding, errors="backslashreplace"), f"Decode error in {encoding}; escaped bytes and raw bytes retained"


def _work_budget(data: bytes, pending: bytes, start: int, encoding: str,
                 discard: bool, max_records: int) -> bytes:
    """Frame at most a bounded number of records before releasing the handle.

    This is byte framing only, not decoding/parsing. Unprocessed bytes stay in
    the source and are read next time, rather than becoming a giant checkpoint.
    """
    buffer = pending + data
    marker = b"\n\x00" if encoding == "utf-16-le" else b"\x00\n" if encoding == "utf-16-be" else b"\n"
    index = 0
    remaining = max_records + int(discard)
    while remaining:
        found = buffer.find(marker, index)
        if found < 0:
            return data
        index = found + len(marker)
        if len(marker) == 2 and (start + found) % 2:
            index = found + 1
            continue
        remaining -= 1
    return data[:max(0, index - len(pending))]


def _anchor_records(data: bytes, start: int, encoding: str):
    """Decode at most 4096 bounded records, with absolute byte positions.

    A window starting inside a record discards that first fragment. Record
    comparison normalizes only encoding and line endings, never log messages.
    This helper is called only after the shared source handle has closed.
    """
    marker = b"\n\x00" if encoding == "utf-16-le" else b"\x00\n" if encoding == "utf-16-be" else b"\n"
    cr = b"\r\x00" if encoding == "utf-16-le" else b"\x00\r" if encoding == "utf-16-be" else b"\r"
    if len(marker) == 2 and start % 2:
        data, start = data[1:], start + 1
    rows = []
    cursor = 0
    while True:
        index = data.find(marker, cursor)
        while index >= 0 and len(marker) == 2 and (start + index) % 2:
            index = data.find(marker, index + 1)
        if index < 0:
            break
        raw = data[cursor:index]
        if raw.endswith(cr):
            raw = raw[:-len(cr)]
        text, _ = _decode(raw, encoding)
        if start + cursor == 0:
            text = text.lstrip("\ufeff")
        rows.append((text, start + cursor, start + index + len(marker)))
        if len(rows) > 4096:
            return None
        cursor = index + len(marker)
    if start > 0 and rows:
        rows = rows[1:]
    partial, _ = _decode(data[cursor:], encoding)
    if start + cursor == 0:
        partial = partial.lstrip("\ufeff")
    return rows, partial


def _rewrite_recovery_point(checkpoint: dict | None, data: bytes, start: int, encoding: str):
    """Return a unique completed-record boundary and historical-discard flag.

    Blank separator changes and partial writes do not invalidate otherwise
    identical records. Repeated or missing meaningful context remains unsafe.
    """
    if not isinstance(checkpoint, dict):
        return None
    try:
        encoded = checkpoint.get("cursor_anchor", "")
        if not isinstance(encoded, str) or len(encoded) > 5464:
            return None
        anchor = base64.b64decode(encoded, validate=True)
        if len(anchor) > 4096:
            return None
        old_start = checkpoint["offset"] - len(anchor)
        old = _anchor_records(anchor, old_start, checkpoint["encoding"])
        new = _anchor_records(data, start, encoding)
        if old is None or new is None:
            return None
        old_rows, old_partial = old
        new_rows, new_partial = new
        old_nonblank = [(i, row) for i, row in enumerate(old_rows) if row[0].strip()]
        new_nonblank = [(i, row) for i, row in enumerate(new_rows) if row[0].strip()]
        discard = bool(checkpoint.get("discard") and old_partial.strip())
        if not old_nonblank:
            # A completely empty/blank baseline, or a new live partial record
            # starting at BOF, has no previously completed scientific records.
            if old_start != 0 or start != 0:
                return None
            if not old_partial.strip() or (checkpoint.get("pending") and checkpoint.get("pending_start") in {0, 2, 3}):
                return 0, False
            # An unterminated historical first line must still be discarded.
            if discard and new_rows and new_rows[0][0].startswith(old_partial):
                return 0, True
            return None
        texts = [row[0] for _, row in old_nonblank]
        if sum(len(text) for text in texts) < 16:
            return None
        candidate_texts = [row[0] for _, row in new_nonblank]
        width = len(texts)
        matches = [i for i in range(len(candidate_texts) - width + 1) if candidate_texts[i:i+width] == texts]
        if len(matches) != 1:
            return None
        last_new_row = new_nonblank[matches[0] + width - 1][0]
        point = new_rows[last_new_row][2]
        # Existing trailing separator lines can be retained, removed, or have
        # the new entry inserted before them. Skip only the known old count.
        old_blanks = len(old_rows) - old_nonblank[-1][0] - 1
        next_index = last_new_row + 1
        while old_blanks and next_index < len(new_rows) and not new_rows[next_index][0].strip():
            point = new_rows[next_index][2]
            next_index += 1
            old_blanks -= 1
        if discard:
            following = new_rows[next_index][0] if next_index < len(new_rows) else new_partial
            if not following.startswith(old_partial):
                return None
        return point, discard
    except (KeyError, TypeError, ValueError, LookupError):
        return None


def read_batch(path: str, checkpoint: dict | None = None, start_mode: str = "new",
               encoding: str = "auto", max_bytes: int = 262144,
               max_record_bytes: int = 65536, max_records: int = 2048,
               reset_policy: str = "review") -> TailBatch:
    if start_mode not in ("new", "review", "resume"):
        raise ValueError("start_mode must be new, review or resume")
    if reset_policy not in {"new", "review"}:
        raise ValueError("reset_policy must be new or review")
    if not 1 <= max_bytes <= 4 * 1024 * 1024 or not 64 <= max_record_bytes <= 1024 * 1024 or not 1 <= max_records <= 10000:
        raise ValueError("Invalid bounded-read or record budget")
    cp = dict(checkpoint) if isinstance(checkpoint, dict) and checkpoint else None
    previous_cp = cp
    diagnostics = []
    recovery_data = b""
    recovery_start = 0
    reset_recovered = False
    # All source access ends before decoding or application work begins.
    with SharedFile(path) as source:
        prefix = source.read_at(0, min(4, source.size))
        detected, bom_length = _detect(prefix, encoding)
        reset = "Invalid checkpoint; possible coverage gap; reading from start" if checkpoint is not None and cp is None else ""
        if cp:
            try:
                _checkpoint_pending(cp, max_record_bytes)
                valid = (cp["identity"] == source.identity
                         and cp["offset"] <= source.size and cp["offset"] >= 0
                         and cp["encoding_override"] == encoding
                         and cp["path"] == str(path))
                boundary_offset = max(0, cp["offset"] - 64)
                boundary = source.read_at(boundary_offset, cp["offset"] - boundary_offset)
                if not valid:
                    reset = "File replacement/truncation or invalid checkpoint; possible coverage gap; reading new generation from start"
                elif hashlib.sha256(boundary).hexdigest() != cp["boundary_hash"]:
                    reset = "Cursor boundary changed (same-file rewrite); possible coverage gap; reading new generation from start"
            except (KeyError, TypeError, ValueError):
                reset = "Invalid checkpoint; possible coverage gap; reading from start"
            if reset:
                if reset_policy == "new":
                    reset = reset.split("; reading", 1)[0]
                diagnostics.append(reset)
                cp = None
            elif encoding in ("auto", "utf-16") and cp["pending_start"] == 0 and cp["offset"] <= 3:
                # An initially empty file, or a BOM written in separate byte
                # writes, has not established its decoder until the BOM exists.
                if detected != cp["encoding"]:
                    cp["encoding"] = detected
                    diagnostics.append(f"Encoding established after initial BOM: {detected}")
                if cp.pop("tentative_bom", False) and not _partial_bom(prefix) and not bom_length:
                    cp["discard"] = True
                    diagnostics.append("Tentative BOM was a historical partial record; discarding through newline")
                elif _partial_bom(prefix) and checkpoint.get("tentative_bom"):
                    cp["tentative_bom"] = True
        if cp is None:
            if reset and reset_policy == "new":
                reset = reset.split("; reading", 1)[0]
            if reset and reset not in diagnostics:
                diagnostics.append(reset)
            baseline = source.size if (not reset and start_mode in ("new", "resume")) or (reset and reset_policy == "new") else (bom_length if source.size >= bom_length else 0)
            if start_mode == "resume" and not checkpoint:
                diagnostics.append("No valid saved checkpoint; starting at current end")
            tail = source.read_at(max(0, baseline - 2), min(2, baseline))
            marker = b"\n\x00" if detected == "utf-16-le" else b"\x00\n" if detected == "utf-16-be" else b"\n"
            discard = baseline > bom_length and not tail.endswith(marker)
            initial_pending = b""
            tentative = encoding in ("auto", "utf-16", "utf-8", "utf-8-sig") and _partial_bom(prefix) and baseline == source.size
            if tentative:
                initial_pending = prefix
                discard = False
            elif discard and detected.startswith("utf-16") and baseline % 2:
                # Retain a half code unit before EOF, particularly the first
                # byte of a historical newline, so its continuation can resync.
                initial_pending = tail[-1:]
            cp = dict(schema=1, path=str(path), identity=source.identity, generation=uuid.uuid4().hex,
                      offset=baseline, pending_start=baseline-len(initial_pending), pending=_b64(initial_pending), discard=discard,
                      encoding=detected, encoding_override=encoding, boundary_hash="")
            if tentative:
                cp["tentative_bom"] = True
            diagnostics.append(f"Encoding: {detected}; " + ("new entries only baseline" if baseline == source.size and start_mode != "review" else "reading existing contents"))
        offset = cp["offset"]
        available = max(0, source.size - offset)
        data = source.read_at(offset, min(max_bytes, available))
        data = _work_budget(data, base64.b64decode(cp["pending"]), cp["pending_start"],
                            cp["encoding"], cp["discard"], max_records)
        end = offset + len(data)
        boundary_start = max(0, end - 64)
        boundary = source.read_at(boundary_start, end - boundary_start)
        anchor_start = max(0, end - 4096)
        cursor_anchor = source.read_at(anchor_start, end - anchor_start)
        backlog = max(0, source.size - end)
        snapshot_end = source.size
        if reset and reset_policy == "new":
            recovery_start = max(0, snapshot_end - 65536)
            recovery_data = source.read_at(recovery_start, snapshot_end - recovery_start)
    # Source handle is closed before attempting text/encoding reconciliation.
    if reset and reset_policy == "new":
        recovery_point = _rewrite_recovery_point(previous_cp, recovery_data, recovery_start, detected)
        anchor_end = recovery_point[0] if recovery_point is not None else None
        if anchor_end is not None:
            discard = recovery_point[1]
            data = _work_budget(recovery_data[anchor_end-recovery_start:], b"", anchor_end, detected, discard, max_records)
            end = anchor_end + len(data)
            boundary_start = max(0, end - 64)
            if boundary_start >= recovery_start:
                cp.update(offset=anchor_end, pending_start=anchor_end, pending="", discard=discard, encoding=detected)
                boundary = recovery_data[boundary_start-recovery_start:end-recovery_start]
                cursor_anchor = recovery_data[max(0, end-4096-recovery_start):end-recovery_start]
                backlog = max(0, snapshot_end - end)
                reset_recovered = True
                diagnostics = ["Source file change observed; completed-record continuity recovered." if item == reset else item for item in diagnostics]
                diagnostics.append("Rewrite reconciled at a unique cursor anchor using complete records; processing only new records. Earlier contents were not replayed.")
            else:
                anchor_end = None
        if anchor_end is None:
            diagnostics.append("New-entries policy: rewrite could not be reconciled unambiguously; existing contents skipped and baseline set at current end. Coverage gap: records added during this rewrite may be missed; future appends will be monitored.")
        if anchor_end is None:
            data = b""
            end = snapshot_end
            backlog = 0
    cp["boundary_hash"] = hashlib.sha256(boundary).hexdigest()
    cp["cursor_anchor"] = _b64(cursor_anchor)
    encoding_used = cp["encoding"]
    pending = base64.b64decode(cp["pending"])
    start = cp["pending_start"]
    buffer = pending + data
    lines = []
    while buffer:
        index, marker_size = _newline(buffer, start, encoding_used)
        if cp["discard"]:
            if index < 0:
                # UTF-16 newline itself may be split between writes/polls.
                keep = 1 if encoding_used.startswith("utf-16") else 0
                consumed = max(0, len(buffer) - keep)
                start += consumed
                buffer = buffer[consumed:]
                break
            cut = index + marker_size
            buffer = buffer[cut:]
            start += cut
            cp["discard"] = False
            continue
        if index < 0 and len(buffer) <= max_record_bytes:
            break
        if index >= 0 and index <= max_record_bytes:
            cut = index + marker_size
            record = buffer[:index]
            cr = b"\r\x00" if encoding_used == "utf-16-le" else b"\x00\r" if encoding_used == "utf-16-be" else b"\r"
            if record.endswith(cr):
                record = record[:-len(cr)]
            text, diagnostic = _decode(record, encoding_used)
            if start == 0:
                text = text.lstrip("\ufeff")
            lines.append(RawLine(start, start + cut, text, _b64(record), diagnostic))
            buffer = buffer[cut:]
            start += cut
        else:
            record = buffer[:max_record_bytes]
            text, diagnostic = _decode(record, encoding_used)
            diagnostic = "Oversized record: bounded prefix retained; discarding through next newline. " + diagnostic
            lines.append(RawLine(start, start + len(record), text, _b64(record), diagnostic))
            diagnostics.append("Oversized record discarded/resynchronizing")
            cp["discard"] = True
            # Keep data available to the discard branch, including any newline.
    cp.update(offset=end, pending=_b64(buffer), pending_start=start)
    return TailBatch(lines, cp, len(data), backlog, diagnostics, encoding_used, reset_recovered)

"""Adversarial reader review: real temporary files, no configured ATLAS paths."""
from __future__ import annotations

import base64
import copy

import pytest

from atlas_watchdog.tailer import read_batch


def append(path, value):
    with path.open("ab") as writer:
        writer.write(value)


@pytest.mark.parametrize(("encoding", "bom"), [("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")])
def test_initially_empty_file_can_receive_utf16_bom_later(tmp_path, encoding, bom):
    path = tmp_path / "empty.log"
    path.write_bytes(b"")
    baseline = read_batch(str(path))
    append(path, bom + "new Error\r\n".encode(encoding))
    batch = read_batch(str(path), baseline.checkpoint)
    assert [line.text for line in batch.lines] == ["new Error"]
    assert batch.encoding == encoding


@pytest.mark.parametrize(("encoding", "bom"), [("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")])
def test_new_baseline_in_middle_of_utf16_newline_keeps_first_new_record(tmp_path, encoding, bom):
    path = tmp_path / "partial-newline.log"
    old = bom + "historical\r\n".encode(encoding)
    path.write_bytes(old[:-1])
    baseline = read_batch(str(path))
    assert not baseline.lines
    append(path, old[-1:] + "new Error\n".encode(encoding))
    batch = read_batch(str(path), baseline.checkpoint)
    assert [line.text for line in batch.lines] == ["new Error"]


@pytest.mark.parametrize(("encoding", "bom"), [("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")])
def test_utf16_bom_created_one_byte_at_a_time_is_not_historical_record(tmp_path, encoding, bom):
    path = tmp_path / "split-bom.log"
    path.write_bytes(bom[:1])
    baseline = read_batch(str(path))
    append(path, bom[1:] + "new Error\n".encode(encoding))
    batch = read_batch(str(path), baseline.checkpoint)
    assert [line.text for line in batch.lines] == ["new Error"]


@pytest.mark.parametrize(("prefix", "symbol"), [(b"\xff", "ÿ"), (b"\xfe", "þ")])
def test_cp1252_first_byte_is_not_a_utf16_bom_without_second_byte(tmp_path, prefix, symbol):
    path = tmp_path / "not-a-bom.log"
    path.write_bytes(prefix + b"Error visible\n")
    batch = read_batch(str(path), start_mode="review")
    assert [line.text for line in batch.lines] == [symbol + "Error visible"]
    assert batch.lines[0].diagnostic.startswith("Strict UTF-8 failed")


def checkpoint_fixture(tmp_path):
    path = tmp_path / "checkpoint.log"
    path.write_bytes(b"old record\n")
    return path, read_batch(str(path), start_mode="review").checkpoint


@pytest.mark.parametrize("missing", ["encoding", "generation", "discard", "pending_start", "boundary_hash", "identity", "offset"])
def test_corrupt_checkpoint_missing_required_field_resets_visibly(tmp_path, missing):
    path, checkpoint = checkpoint_fixture(tmp_path)
    del checkpoint[missing]
    batch = read_batch(str(path), checkpoint, start_mode="resume")
    assert any("checkpoint" in diagnostic.lower() or "gap" in diagnostic.lower() for diagnostic in batch.diagnostics)
    assert batch.checkpoint["generation"]
    assert batch.checkpoint["encoding"] in {"auto-8bit", "utf-8", "utf-16-le", "utf-16-be", "cp1252"}


@pytest.mark.parametrize("encoding", ["not-a-real-codec", "utf-7", None, 123])
def test_corrupt_checkpoint_encoding_cannot_change_decoder_or_crash(tmp_path, encoding):
    path, checkpoint = checkpoint_fixture(tmp_path)
    checkpoint["encoding"] = encoding
    append(path, b"new Error\n")
    batch = read_batch(str(path), checkpoint, start_mode="resume")
    assert any("checkpoint" in diagnostic.lower() or "gap" in diagnostic.lower() for diagnostic in batch.diagnostics)
    assert any(line.text == "new Error" for line in batch.lines)


def test_corrupt_discard_suffix_is_rejected_instead_of_skipping_new_data(tmp_path):
    path, checkpoint = checkpoint_fixture(tmp_path)
    checkpoint.update(discard=True, pending=base64.b64encode(b"forged suffix").decode(), pending_start=-200)
    append(path, b"new Error\n")
    batch = read_batch(str(path), checkpoint, start_mode="resume")
    assert any("checkpoint" in diagnostic.lower() or "gap" in diagnostic.lower() for diagnostic in batch.diagnostics)
    assert any(line.text == "new Error" for line in batch.lines)


def test_checkpoint_input_is_not_mutated_even_on_reset(tmp_path):
    path, checkpoint = checkpoint_fixture(tmp_path)
    original = copy.deepcopy(checkpoint)
    path.write_bytes(b"rewrite\n")
    read_batch(str(path), checkpoint, start_mode="resume")
    assert checkpoint == original


@pytest.mark.parametrize(("encoding", "bom"), [("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")])
def test_utf16_huge_record_resynchronizes_at_aligned_boundary(tmp_path, encoding, bom):
    path = tmp_path / "huge-utf16.log"
    path.write_bytes(bom + ("X" * 150 + "\nnew Error\n").encode(encoding))
    checkpoint = None
    lines = []
    for _ in range(200):
        batch = read_batch(str(path), checkpoint, start_mode="review", max_bytes=7, max_record_bytes=65)
        checkpoint = batch.checkpoint
        lines.extend(batch.lines)
        assert len(base64.b64decode(checkpoint["pending"])) <= 65
        if not batch.backlog:
            break
    assert len([line for line in lines if line.diagnostic.startswith("Oversized")]) == 1
    assert lines[-1].text == "new Error"


def test_bounded_read_snapshot_excludes_later_appends(tmp_path, monkeypatch):
    import atlas_watchdog.tailer as tailer
    path = tmp_path / "snapshot.log"
    path.write_bytes(b"first\n")
    original = tailer.SharedFile

    class GrowingFile(original):
        def __enter__(self):
            result = super().__enter__()
            append(path, b"later\n")
            return result

    monkeypatch.setattr(tailer, "SharedFile", GrowingFile)
    first = read_batch(str(path), start_mode="review")
    assert [line.text for line in first.lines] == ["first"]
    monkeypatch.setattr(tailer, "SharedFile", original)
    next_batch = read_batch(str(path), first.checkpoint)
    assert [line.text for line in next_batch.lines] == ["later"]

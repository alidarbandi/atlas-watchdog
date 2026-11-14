import base64
import ctypes
import hashlib
import json
import os

import pytest

from atlas_watchdog.file_access import SharedFile
from atlas_watchdog.tailer import read_batch


def append(path, value):
    with path.open("ab") as writer:
        writer.write(value)


def test_partial_and_crlf_restart_transaction(tmp_path):
    path = tmp_path / "log"
    path.write_bytes(b"one\r\ntw")
    batch = read_batch(str(path), start_mode="review", max_bytes=7)
    assert [x.text for x in batch.lines] == ["one"]
    cp = json.loads(json.dumps(batch.checkpoint))
    append(path, b"o\r")
    next_batch = read_batch(str(path), cp)
    assert not next_batch.lines
    append(path, b"\nthree\n")
    result = read_batch(str(path), next_batch.checkpoint)
    assert [x.text for x in result.lines] == ["two", "three"]
    # Crash before committing: same input checkpoint replays the exact records.
    replay = read_batch(str(path), next_batch.checkpoint)
    assert [(x.offset, x.text) for x in replay.lines] == [(x.offset, x.text) for x in result.lines]
    assert replay.checkpoint["generation"] == result.checkpoint["generation"]


def test_new_entries_partial_history_not_alerted(tmp_path):
    path = tmp_path / "log"
    path.write_bytes(b"old\nError partial")
    baseline = read_batch(str(path))
    assert not baseline.lines
    append(path, b" completion\nnew Error\n")
    batch = read_batch(str(path), baseline.checkpoint)
    assert [x.text for x in batch.lines] == ["new Error"]


@pytest.mark.parametrize("enc,bom", [("utf-8", b"\xef\xbb\xbf"), ("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")])
def test_split_codepoints_newlines_and_bom(tmp_path, enc, bom):
    path = tmp_path / "log"
    original = "µ° lab\r\nError\n"
    payload = bom + original.encode(enc)
    path.write_bytes(payload)
    cp = None
    texts = []
    for _ in range(len(payload) + 5):
        batch = read_batch(str(path), cp, start_mode="review", max_bytes=1)
        texts.extend(x.text for x in batch.lines)
        cp = batch.checkpoint
        if not batch.backlog:
            break
    assert texts == ["µ° lab", "Error"]


def test_cp1252_fallback_and_raw_bytes(tmp_path):
    path = tmp_path / "log"
    path.write_bytes(b"test \xb5\xb0\nundefined\x81\n")
    batch = read_batch(str(path), start_mode="review")
    assert batch.lines[0].text == "test µ°"
    assert batch.lines[0].diagnostic
    assert base64.b64decode(batch.lines[1].raw_b64) == b"undefined\x81"
    assert "\\x81" in batch.lines[1].text


def test_huge_record_bounded_and_later_error_recovered(tmp_path):
    path = tmp_path / "log"
    path.write_bytes(b"A" * 2000 + b"\nError later\n")
    cp = None
    rows = []
    for _ in range(30):
        batch = read_batch(str(path), cp, start_mode="review", max_bytes=100, max_record_bytes=64)
        cp = batch.checkpoint
        rows.extend(batch.lines)
        assert len(base64.b64decode(cp["pending"])) <= 64
        if not batch.backlog:
            break
    assert rows[0].diagnostic.startswith("Oversized")
    assert rows[-1].text == "Error later"
    assert sum(bool(x.diagnostic.startswith("Oversized")) for x in rows) == 1


def test_same_size_replacement_and_same_file_rewrite(tmp_path):
    path = tmp_path / "log"
    path.write_bytes(b"before\n")
    old = read_batch(str(path), start_mode="review")
    replacement = tmp_path / "new"
    replacement.write_bytes(b"after!\n")
    os.replace(replacement, path)
    new = read_batch(str(path), old.checkpoint)
    assert new.lines[0].text == "after!"
    assert new.checkpoint["generation"] != old.checkpoint["generation"]
    assert any("coverage gap" in x for x in new.diagnostics)
    path.write_bytes(b"again!\n")
    rewrite = read_batch(str(path), new.checkpoint)
    assert rewrite.lines[0].text == "again!"
    assert any("rewrite" in x for x in rewrite.diagnostics)


def test_truncation_and_bounded_backlog(tmp_path):
    path = tmp_path / "log"
    path.write_bytes(b"line\n" * 100)
    batch = read_batch(str(path), start_mode="review", max_bytes=20)
    assert batch.bytes_read == 20
    assert batch.backlog == 480
    path.write_bytes(b"new\n")
    batch = read_batch(str(path), batch.checkpoint)
    assert batch.lines[0].text == "new"


def test_directory_metadata_not_consulted(tmp_path, monkeypatch):
    path = tmp_path / "log"
    path.write_bytes(b"Error actual bytes\n")
    # A stale enumeration/stat entry must never gate the read. Raising is stronger
    # than a zero length: any directory metadata dependency fails this test.
    import atlas_watchdog.file_access as access
    from types import SimpleNamespace
    with monkeypatch.context() as patch:
        patch.setattr(access.os.path, "getsize", lambda _: 0)
        patch.setattr(access.os, "stat", lambda *args, **kwargs: SimpleNamespace(st_size=0))
        batch = read_batch(str(path), start_mode="review")
    assert batch.lines[0].text == "Error actual bytes"


def test_read_leaves_source_unchanged_and_closes_handle(tmp_path):
    path = tmp_path / "log"
    content = b"one\ntwo\n"
    path.write_bytes(content)
    assert read_batch(str(path), start_mode="review").lines
    assert path.read_bytes() == content
    # Rename immediately after the call must succeed; no retained handles.
    path.rename(tmp_path / "renamed")


@pytest.mark.skipif(os.name != "nt", reason="Windows CreateFile sharing acceptance")
def test_windows_actual_shared_writer_and_exclusive_conflict(tmp_path):
    import atlas_watchdog.file_access as access
    from ctypes import wintypes
    path = tmp_path / "writer.log"
    path.write_bytes(b"one\n")
    kernel = access._kernel
    writer = kernel.CreateFileW(str(path), 0x40000000, 7, None, 3, 0, None)
    assert writer != ctypes.c_void_p(-1).value
    try:
        kernel.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        kernel.WriteFile.restype = wintypes.BOOL
        assert kernel.SetFilePointerEx(writer, 0, None, 2)
        written = wintypes.DWORD()
        assert kernel.WriteFile(writer, b"two\n", 4, ctypes.byref(written), None)
        batch = read_batch(str(path), start_mode="review")
        assert [x.text for x in batch.lines] == ["one", "two"]
    finally:
        kernel.CloseHandle(writer)
    exclusive = kernel.CreateFileW(str(path), 0x40000000, 0, None, 3, 0, None)
    assert exclusive != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(OSError):
            read_batch(str(path), batch.checkpoint)
    finally:
        kernel.CloseHandle(exclusive)
    assert not read_batch(str(path), batch.checkpoint).lines


@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive reopen limitation")
def test_windows_exclusive_reopen_conflicts_only_while_reader_open(tmp_path):
    import atlas_watchdog.file_access as access
    path = tmp_path / "writer.log"
    path.write_bytes(b"one\n")
    with SharedFile(path):
        exclusive = access._kernel.CreateFileW(str(path), 0x40000000, 0, None, 3, 0, None)
        if exclusive != ctypes.c_void_p(-1).value:
            access._kernel.CloseHandle(exclusive)
            pytest.fail("Exclusive writer should conflict with an outstanding reader")
        assert ctypes.get_last_error() == 32
    exclusive = access._kernel.CreateFileW(str(path), 0x40000000, 0, None, 3, 0, None)
    assert exclusive != ctypes.c_void_p(-1).value
    access._kernel.CloseHandle(exclusive)


def test_windows_flags_are_read_only_shared_and_existing(monkeypatch, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows wrapper flags")
    import atlas_watchdog.file_access as access
    path = tmp_path / "source.log"
    path.write_bytes(b"one\n")
    original = access._kernel.CreateFileW
    calls = []

    def tracked(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(access._kernel, "CreateFileW", tracked)
    read_batch(str(path), start_mode="review")
    assert len(calls) == 1
    assert calls[0][1:5] == (0x80000000, 7, None, 3)


def test_empty_and_blank_unknown_records(tmp_path):
    path = tmp_path / "log"
    path.write_bytes(b"\ncustom\n")
    result = read_batch(str(path), start_mode="review")
    assert [x.text for x in result.lines] == ["", "custom"]


def test_record_work_budget_leaves_backlog_in_source_not_checkpoint(tmp_path):
    path = tmp_path / "many-blank.log"
    path.write_bytes(b"\n" * 10000 + b"Error later\n")
    cp = None
    lines = []
    while True:
        batch = read_batch(str(path), cp, start_mode="review", max_records=100)
        assert len(batch.lines) <= 100
        assert len(base64.b64decode(batch.checkpoint["pending"])) == 0
        lines.extend(batch.lines)
        cp = batch.checkpoint
        if not batch.backlog:
            break
    assert len(lines) == 10001
    assert lines[-1].text == "Error later"


def test_utf16_discard_boundary_split(tmp_path):
    path = tmp_path / "log"
    path.write_bytes(b"\xff\xfe" + "old partial".encode("utf-16-le"))
    baseline = read_batch(str(path))
    append(path, " end\nnew\n".encode("utf-16-le"))
    cp = baseline.checkpoint
    rows = []
    for _ in range(30):
        batch = read_batch(str(path), cp, max_bytes=1)
        cp = batch.checkpoint
        rows.extend(batch.lines)
        if not batch.backlog:
            break
    assert [x.text for x in rows] == ["new"]

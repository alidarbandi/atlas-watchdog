import copy

import pytest

from atlas_watchdog.controller import Controller
from atlas_watchdog.tailer import read_batch


def log(message, level="Info"):
    return f"13/11/2026\t15:00:00.000\t{level}\tSystem\t\t{message}\r\n"


@pytest.mark.parametrize("replace", [False, True])
def test_editor_save_with_encoding_change_emits_only_new_suffix(tmp_path, replace):
    path = tmp_path / "test.log"
    # Changes before the cursor shift byte offsets when an editor saves UTF-8.
    old = log("Old historical fault", "Error") + (log("Temperature 35.0°; distance 0.0325 µm") * 300)
    old += log("Unique final baseline record")
    path.write_bytes(old.encode("cp1252"))
    baseline = read_batch(str(path), reset_policy="new")
    fresh = log("Turning SEM EHT off")
    if replace:
        replacement = tmp_path / "replacement.log"
        replacement.write_bytes((old + fresh).encode("utf-8"))
        replacement.replace(path)
    else:
        path.write_bytes((old + fresh).encode("utf-8"))
    batch = read_batch(str(path), baseline.checkpoint, reset_policy="new")
    assert [r.text for r in batch.lines] == [fresh.rstrip("\r\n")]
    assert any("unique cursor anchor" in d for d in batch.diagnostics)
    assert not any("reading new generation from start" in d for d in batch.diagnostics)
    assert not read_batch(str(path), batch.checkpoint, reset_policy="new").lines


def test_ambiguous_replacement_baselines_end_and_reports_coverage_gap(tmp_path):
    path = tmp_path / "test.log"
    path.write_bytes(log("Original cursor record").encode())
    baseline = read_batch(str(path), reset_policy="new")
    replacement = tmp_path / "replacement.log"
    replacement.write_bytes(log("Unrelated prior fault", "Error").encode())
    replacement.replace(path)
    batch = read_batch(str(path), baseline.checkpoint, reset_policy="new")
    assert not batch.lines and batch.backlog == 0
    assert any("records added during this rewrite may be missed" in d for d in batch.diagnostics)
    with path.open("ab") as writer:
        writer.write(log("Fresh fault after new baseline", "Error").encode())
    next_batch = read_batch(str(path), batch.checkpoint, reset_policy="new")
    assert len(next_batch.lines) == 1 and "Fresh fault" in next_batch.lines[0].text


def test_repeated_anchor_does_not_guess_or_replay_history(tmp_path):
    path = tmp_path / "test.log"
    old = log("Repeated baseline marker")
    path.write_bytes(old.encode())
    baseline = read_batch(str(path), reset_policy="new")
    replacement = tmp_path / "replace.log"
    replacement.write_bytes((old + old + log("Fault", "Error")).encode())
    replacement.replace(path)
    batch = read_batch(str(path), baseline.checkpoint, reset_policy="new")
    assert not batch.lines
    assert any("unambiguously" in d for d in batch.diagnostics)


def test_large_engineering_log_rewrite_does_not_replay_old_errors(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    path = folder / "execution_log.log"
    old = log("Historical microscope fault", "Error")
    old += log("Repeated temperature 35.4° and distance 0.0325 µm") * 33000
    old += log("Unique final baseline record")
    path.write_bytes(old.encode("cp1252"))
    c = Controller(tmp_path / "state")
    try:
        settings = copy.deepcopy(c.config)
        settings["mode"] = "execution"
        settings["sources"]["execution"]["folder"] = str(folder)
        next(r for r in settings["rules"]["execution"] if r["pattern"] == "Turning SEM EHT off")["enabled"] = True
        c.handle("configure", settings)
        c.handle("start", {"mode":"new"})
        c._poll("execution")
        assert not c.store.events()
        path.write_bytes((old + log("Turning SEM EHT off")).encode("utf-8"))
        c._poll("execution")
        matches = [e for e in c.store.events() if e["kind"] == "match"]
        assert len(matches) == 1 and matches[0]["message"] == "Turning SEM EHT off"
        assert not matches[0]["historical"]
        assert not c.sources["execution"]["backlog"]
        assert not any(e["message"] == "Historical microscope fault" for e in c.store.events())
        assert not any(e["kind"] == "coverage" for e in c.store.events())
        assert any(e["kind"] == "source-change" and e["severity"] == "info" for e in c.store.events())
    finally:
        c.close()


def test_truncation_in_new_only_does_not_replay(tmp_path):
    path = tmp_path / "test.log"
    path.write_bytes((log("Old fault", "Error") * 20).encode())
    baseline = read_batch(str(path), reset_policy="new")
    path.write_bytes(log("Short rewritten fault", "Error").encode())
    batch = read_batch(str(path), baseline.checkpoint, reset_policy="new")
    assert not batch.lines
    assert batch.checkpoint["offset"] == path.stat().st_size


def test_explicit_historical_review_still_can_read_replacement(tmp_path):
    path = tmp_path / "test.log"
    path.write_bytes(log("First record").encode())
    baseline = read_batch(str(path), start_mode="review")
    path.write_bytes(log("Rewritten old fault", "Error").encode())
    review = read_batch(str(path), baseline.checkpoint, start_mode="review", reset_policy="review")
    assert len(review.lines) == 1 and "Rewritten old fault" in review.lines[0].text


def test_rewrite_suffix_keeps_record_budget_and_continues_from_checkpoint(tmp_path):
    path = tmp_path / "test.log"
    old = log("Unique old final marker")
    path.write_bytes(old.encode())
    baseline = read_batch(str(path), reset_policy="new")
    replacement = tmp_path / "replacement.log"
    replacement.write_bytes((old + log("New first fault", "Error") + log("New second fault", "Error")).encode())
    replacement.replace(path)
    first = read_batch(str(path), baseline.checkpoint, reset_policy="new", max_records=1)
    assert len(first.lines)==1 and "New first fault" in first.lines[0].text and first.backlog > 0
    second = read_batch(str(path), first.checkpoint, reset_policy="new", max_records=1)
    assert len(second.lines)==1 and "New second fault" in second.lines[0].text and second.backlog == 0


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_rewrite_to_utf16_recovers_only_added_records(tmp_path, encoding):
    path = tmp_path / "test.log"
    old = log("Historical error 35°", "Error") + log("Unique final marker µm")
    path.write_bytes(old.encode("cp1252"))
    baseline = read_batch(str(path), reset_policy="new")
    bom = b"\xff\xfe" if encoding=="utf-16-le" else b"\xfe\xff"
    replacement = tmp_path / "replacement.log"
    replacement.write_bytes(bom + (old + log("New fault", "Error")).encode(encoding))
    replacement.replace(path)
    batch = read_batch(str(path), baseline.checkpoint, reset_policy="new")
    assert len(batch.lines)==1 and "New fault" in batch.lines[0].text


def test_recovery_scan_is_bounded_and_does_not_guess_distant_anchor(tmp_path):
    path = tmp_path / "test.log"
    old = log("Original cursor marker")
    path.write_bytes(old.encode())
    baseline = read_batch(str(path), reset_policy="new")
    replacement = tmp_path / "replacement.log"
    replacement.write_bytes((old + log("A new record " + "x"*200)*500).encode())
    replacement.replace(path)
    batch = read_batch(str(path), baseline.checkpoint, reset_policy="new")
    assert not batch.lines
    assert any("records added during this rewrite may be missed" in d for d in batch.diagnostics)


def test_editor_inserts_new_record_before_existing_trailing_blank_lines(tmp_path):
    path=tmp_path/'test.log'
    old=log('Historical fault','Error')+log('Unique final baseline marker')
    path.write_bytes((old+'\r\n'*5).encode())
    baseline=read_batch(str(path),reset_policy='new')
    path.write_bytes((old+log('Turning SEM EHT off')+'\r\n'*2).encode())
    batch=read_batch(str(path),baseline.checkpoint,reset_policy='new')
    assert [r.text for r in batch.lines if r.text.strip()]==[log('Turning SEM EHT off').rstrip('\r\n')]
    assert not any('could not be reconciled' in d for d in batch.diagnostics)


def test_live_partial_record_can_finish_during_atomic_editor_rewrite(tmp_path):
    path=tmp_path/'test.log'
    old=log('Unique historical baseline marker')
    path.write_bytes(old.encode())
    baseline=read_batch(str(path),reset_policy='new')
    with path.open('ab') as writer:
        writer.write(b'13/11/2026\t20:49:00.621\tInfo\tSystem\t\tTurning SEM')
    partial=read_batch(str(path),baseline.checkpoint,reset_policy='new')
    assert partial.checkpoint['pending'] and not partial.lines
    replacement=tmp_path/'replacement.log'
    replacement.write_bytes((old+log('Turning SEM EHT off')).encode())
    replacement.replace(path)
    batch=read_batch(str(path),partial.checkpoint,reset_policy='new')
    assert len(batch.lines)==1 and 'Turning SEM EHT off' in batch.lines[0].text
    assert not any('could not be reconciled' in d for d in batch.diagnostics)


def test_historical_partial_is_still_discarded_when_rewrite_finishes_it(tmp_path):
    path=tmp_path/'test.log'
    old=log('Historical complete marker')+'Historical error still incomplete'
    path.write_bytes(old.encode())
    baseline=read_batch(str(path),reset_policy='new')
    assert baseline.checkpoint['discard']
    replacement=tmp_path/'replacement.log'
    replacement.write_bytes((old+' now complete\r\n'+log('Fresh fault','Error')).encode())
    replacement.replace(path)
    batch=read_batch(str(path),baseline.checkpoint,reset_policy='new')
    assert len(batch.lines)==1 and 'Fresh fault' in batch.lines[0].text


def test_historical_first_partial_without_any_complete_context(tmp_path):
    path=tmp_path/'test.log'
    path.write_bytes(b'Historical unfinished error')
    baseline=read_batch(str(path),reset_policy='new')
    replacement=tmp_path/'replacement.log'
    replacement.write_bytes(b'Historical unfinished error complete\r\n'+log('New fault','Error').encode())
    replacement.replace(path)
    batch=read_batch(str(path),baseline.checkpoint,reset_policy='new')
    assert len(batch.lines)==1 and 'New fault' in batch.lines[0].text


def test_empty_baseline_atomic_save_can_deliver_first_new_record(tmp_path):
    path=tmp_path/'test.log'
    path.write_bytes(b'')
    baseline=read_batch(str(path),reset_policy='new')
    replacement=tmp_path/'replacement.log'
    replacement.write_bytes(log('First new fault','Error').encode())
    replacement.replace(path)
    batch=read_batch(str(path),baseline.checkpoint,reset_policy='new')
    assert len(batch.lines)==1 and 'First new fault' in batch.lines[0].text


def test_first_live_partial_can_complete_after_editor_save(tmp_path):
    path=tmp_path/'test.log'
    path.write_bytes(b'')
    baseline=read_batch(str(path),reset_policy='new')
    path.write_bytes(b'13/11/2026\t15:00:00.000\tInfo\tSystem\t\tTurning SEM')
    partial=read_batch(str(path),baseline.checkpoint,reset_policy='new')
    replacement=tmp_path/'replacement.log'
    replacement.write_bytes(log('Turning SEM EHT off').encode())
    replacement.replace(path)
    batch=read_batch(str(path),partial.checkpoint,reset_policy='new')
    assert len(batch.lines)==1 and 'Turning SEM EHT off' in batch.lines[0].text


def test_record_matching_allows_line_ending_and_blank_separator_changes(tmp_path):
    path=tmp_path/'test.log'
    old=log('Historical error','Error')+log('Old final marker')+'\r\n'*5
    path.write_bytes(old.encode())
    baseline=read_batch(str(path),reset_policy='new')
    path.write_bytes((old.rstrip('\r\n')+'\r\n'+log('Fresh EHT','Error')).replace('\r\n','\n').encode())
    batch=read_batch(str(path),baseline.checkpoint,reset_policy='new')
    assert len(batch.lines)==1 and 'Fresh EHT' in batch.lines[0].text


def test_changed_historical_partial_is_not_misrepresented_as_new(tmp_path):
    path=tmp_path/'test.log'
    path.write_bytes((log('Old complete marker')+'Historical partial').encode())
    baseline=read_batch(str(path),reset_policy='new')
    path.write_bytes((log('Old complete marker')+log('Changed old partial','Error')+log('Fresh fault','Error')).encode())
    batch=read_batch(str(path),baseline.checkpoint,reset_policy='new')
    assert not batch.lines
    assert any('could not be reconciled' in d for d in batch.diagnostics)

import copy

from atlas_watchdog.controller import Controller
from atlas_watchdog.parser import parse_line


def test_observed_engine_header_retained_without_warning():
    row = parse_line("Application log", "engine", raw_b64="QXBwbGljYXRpb24gbG9n")
    assert row["record_type"] == "header" and row["level"] == "Info"
    assert row["diagnostic"] == "" and row["raw_line"] == "Application log" and row["raw_b64"]


def test_header_exception_does_not_hide_errors_or_other_source_text():
    for source, text in [("engine", "Application log Error: failed"), ("execution", "Application log")]:
        row = parse_line(text, source)
        assert row["diagnostic"] and row["record_type"] == "unstructured"
    assert parse_line("Application log", "engine", diagnostic="Oversized record")["diagnostic"] == "Oversized record"
    row = parse_line("05/11/2026\t10:57:06.495\tError\tApplication\tApplication log", "engine")
    assert row["record_type"] == "record" and row["level"] == "Error"


def test_blank_separator_retained_without_warning():
    row = parse_line("  \t", "engine")
    assert row["record_type"] == "separator" and row["diagnostic"] == ""
    assert row["raw_line"] == "  \t"


def controller(tmp_path, content):
    c = Controller(tmp_path / "state")
    folder = tmp_path / "logs"
    folder.mkdir()
    path = folder / "atlasengine.log"
    path.write_bytes(content)
    config = copy.deepcopy(c.config)
    config["mode"] = "engine"
    config["sources"]["engine"]["folder"] = str(folder)
    c.handle("configure", config)
    c.handle("start", {"mode":"review"})
    return c, path


def line(message, level="Error"):
    return f"13/11/2026\t15:00:00.000\t{level}\tSystem\t\t{message}\r\n".encode()


def test_review_header_and_separators_show_live_without_false_events(tmp_path):
    c, path = controller(tmp_path, b"Application log\r\n\r\n" + line("Temperature reading", "Log"))
    try:
        c._poll("engine")
        assert not c.store.events()
        assert "Application log" in c.live["engine"]
        assert c.sources["engine"]["checkpoint"]["offset"] == path.stat().st_size
    finally: c.close()


def test_restarting_review_has_no_context_from_previous_end(tmp_path):
    c, path = controller(tmp_path, line("First fault") + line("Later temperature", "Log"))
    try:
        c._poll("engine")
        assert "Later temperature" in c.context["engine"][-1]
        c.handle("start", {"mode":"review"})
        c._poll("engine")
        assert all(e["context"] == [] for e in c.store.events() if e["message"] == "First fault")
    finally: c.close()


def test_replacement_starts_fresh_context(tmp_path):
    c, path = controller(tmp_path, line("Prior generation", "Log"))
    try:
        c._poll("engine")
        replacement = path.parent / "replacement.log"
        replacement.write_bytes(line("New generation fault"))
        replacement.replace(path)
        c._poll("engine")
        # New-generation contents are not silently replayed after review ended.
        assert not any(e["message"] == "New generation fault" for e in c.store.events())
        with path.open("ab") as out:
            out.write(line("New generation fault"))
        c._poll("engine")
        event = next(e for e in c.store.events() if e["message"] == "New generation fault")
        assert event["context"] == []
    finally: c.close()

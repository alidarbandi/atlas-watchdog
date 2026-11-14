import copy

import pytest

from atlas_watchdog.controller import Controller, source_read_error


def windows_error(code):
    error = OSError("Simulated failure")
    error.winerror = code
    return error


@pytest.mark.parametrize("code,expected", [(3,"Source folder not found"),(2,"Log file not found"),
                                           (5,"access denied"),(32,"file sharing"),(33,"file sharing"),
                                           (53,"network path unavailable"),(67,"network path unavailable")])
def test_windows_read_failures_have_distinct_actionable_messages(code, expected):
    assert expected in source_read_error(windows_error(code))


def test_missing_folder_event_is_watchdog_health_not_a_malformed_log(tmp_path, monkeypatch):
    c = Controller(tmp_path / "state")
    try:
        settings = copy.deepcopy(c.config)
        settings["mode"] = "engine"
        settings["sources"]["engine"]["folder"] = str(tmp_path / "missing")
        c.handle("configure", settings)
        c.handle("start")
        def fail(*args, **kwargs):
            raise windows_error(3)
        monkeypatch.setattr("atlas_watchdog.controller.read_batch", fail)
        c._poll("engine")
        event = c.store.events()[0]
        assert event["message"].startswith("Source folder not found")
        assert event["origin"] == "watchdog"
        assert event["level"] == "Not applicable"
        assert event["raw_line"] == event["diagnostic"] == ""
        assert not (tmp_path / "missing").exists()
        with pytest.raises(ValueError, match="Source folder not found"):
            c.handle("validate", {"source":"engine"})
    finally:
        c.close()

import base64

from atlas_watchdog.parser import parse_line


def test_explicit_day_month_and_message_tabs():
    line = "05/11/2026\t10:57:06.495\tinfo\tApplication\t\tfirst\tsecond"
    row = parse_line(line, "engine")
    assert row["timestamp_iso"] == "2026-11-05T10:57:06.495000"
    assert row["level"] == "Info"
    assert row["message"] == "first\tsecond"
    assert row["raw_line"] == line
    assert row["receipt_utc"].endswith("+00:00")


def test_unknown_level_and_bad_timestamp_visible():
    row = parse_line("bad\ttime\tCUSTOM\tthing\tError still visible", "execution")
    assert row["level"] == "CUSTOM"
    assert "Error" in row["message"]
    assert row["diagnostic"]


def test_malformed_record_preserved():
    row = parse_line("Error: invalid record", "execution", "RXJyb3I=", "bad decode")
    assert row["message"] == "Error: invalid record"
    assert "Malformed" in row["diagnostic"]
    assert row["raw_b64"] == "RXJyb3I="


def test_warning_case_and_timezone():
    row = parse_line("05/11/2026\t10:57:06.495\tWARN\tTest\tmessage", "engine", source_timezone="Etc/UTC")
    assert row["level"] == "Warning"
    assert row["timestamp_iso"].endswith("+00:00")

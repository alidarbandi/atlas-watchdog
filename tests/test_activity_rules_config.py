"""Deterministic watch/rule policies and secret-free configuration boundaries."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from atlas_watchdog.activity import ActivityWatch
from atlas_watchdog.config import (
    ConfigStore, defaults, merge_defaults, portable_config, preset_rules,
    safe_destination, source_path, validate,
)
from atlas_watchdog.rules import evaluate, matches


def policy(**changes):
    result = defaults()["sources"]["execution"]
    result.update(expect_activity=True, grace=0, cycles=3, reminder_seconds=0)
    result.update(changes)
    return result


def record(message="plain activity", level="Info", component="Atlas 3D"):
    return dict(message=message, level=level, component=component,
                raw_line=f"09/09/2026\t13:00:00.000\t{level}\t{component}\t{message}")


def literal(pattern="problem", **changes):
    rule = preset_rules("engine")[1]
    rule.update(id="custom", name="Custom", enabled=True, pattern=pattern)
    rule.update(changes)
    return rule


def test_cycle_mode_counts_only_successful_empty_polls_and_new_bytes_recover():
    watch = ActivityWatch(policy(), 100)
    assert watch.poll(110, success=True, new_bytes=0) == []
    assert watch.poll(120, success=False, new_bytes=0) == []
    assert watch.empty_cycles == 1
    assert watch.poll(130, success=True, new_bytes=0) == []
    incident = watch.poll(140, success=True, new_bytes=0)
    assert len(incident) == 1 and incident[0]["kind"] == "silence"
    assert "possible stalled acquisition" in incident[0]["message"]
    assert "40.0 s" in incident[0]["message"]
    assert watch.poll(150, success=True, new_bytes=0) == []
    recovery = watch.poll(160, success=True, new_bytes=7)
    assert recovery[0]["kind"] == "silence-recovery" and recovery[0]["notify"] is False
    assert watch.empty_cycles == 0 and watch.last_bytes == 160
    assert watch.last_record == 100  # Bytes are distinct from valid record progress.


def test_duration_watch_uses_elapsed_clock_after_healthy_empty_confirmation():
    watch = ActivityWatch(policy(inactivity_mode="duration", duration=300), 10)
    assert watch.poll(309.999, success=True, new_bytes=0) == []
    assert watch.poll(310, success=False, new_bytes=0) == []
    assert watch.poll(311, success=True, new_bytes=0)[0]["kind"] == "silence"


def test_startup_grace_and_backlog_cannot_produce_silence_incident():
    watch = ActivityWatch(policy(grace=60, cycles=1), 100)
    assert watch.poll(110, success=True, new_bytes=0) == []
    assert "grace" in watch.status(110)
    assert watch.poll(160, success=True, new_bytes=0, caught_up=False) == []
    assert watch.poll(170, success=True, new_bytes=0)[0]["kind"] == "silence"


def test_sources_have_independent_activity_and_incidents():
    execution = ActivityWatch(policy(cycles=1), 0)
    engine = ActivityWatch(policy(cycles=1), 0)
    assert engine.poll(10, success=True, new_bytes=100) == []
    assert execution.poll(10, success=True, new_bytes=0)[0]["kind"] == "silence"
    assert execution.last_bytes == 0 and engine.last_bytes == 10
    assert engine.incidents == {} and "silence" in execution.incidents


def test_manual_pause_resume_starts_grace_without_changing_keyword_rules():
    watch = ActivityWatch(policy(grace=60, cycles=1), 0)
    watch.update_policy(policy(expect_activity=False, grace=60, cycles=1), 100)
    assert watch.poll(1000, success=True, new_bytes=0) == []
    assert "Not armed" in watch.status(1000)
    assert evaluate(preset_rules("execution"), record("fault", "Error"))["matched"]
    watch.update_policy(policy(grace=60, cycles=1), 1001)
    assert watch.poll(1010, success=True, new_bytes=0) == []
    assert watch.poll(1061, success=True, new_bytes=0)[0]["kind"] == "silence"


def test_heartbeat_sample_intervals_above_two_minutes_are_not_failures():
    watch = ActivityWatch(policy(heartbeat=True, cycles=100, heartbeat_seconds=300), 0)
    for timestamp in [132, 264, 451]:
        watch.record(record("Process is alive. ImageNo:1; MillZ:0.0000 µm"), timestamp)
        assert watch.poll(timestamp, success=True, new_bytes=70) == []
    assert watch.poll(750, success=True, new_bytes=1) == []
    assert watch.poll(751, success=True, new_bytes=1)[0]["kind"] == "heartbeat"


def test_unchanged_heartbeat_is_liveness_without_progress():
    watch = ActivityWatch(policy(heartbeat=True, progress=True, cycles=100,
                                 heartbeat_seconds=300, progress_seconds=600), 0)
    for timestamp in [100, 250, 400, 550]:
        watch.record(record("Process is alive. ImageNo:1; MillZ:0.0000 µm"), timestamp)
        assert watch.poll(timestamp, success=True, new_bytes=10) == []
    incident = watch.poll(600, success=True, new_bytes=10)
    assert [event["kind"] for event in incident] == ["progress"]
    watch.record(record("Process is alive. ImageNo:2; MillZ:0.0000 µm"), 610)
    recovery = watch.poll(610, success=True, new_bytes=10)
    assert [event["kind"] for event in recovery] == ["progress-recovery"]


def test_progress_requires_completion_or_advancement_not_acquisition_attempts():
    watch = ActivityWatch(policy(), 0)
    watch.record(record("Acquiring slice_00001_z=0.0000um.tif"), 10)
    watch.record(record("Acquiring slice_00001_z=0.0000um.tif"), 20)
    assert watch.last_progress == 0
    watch.record(record("ImageNo:1; MillZ:0.0 µm"), 30)
    assert watch.last_progress == 0
    watch.record(record("ImageNo:1; MillZ:0.1 µm"), 40)
    assert watch.last_progress == 40
    watch.record(record("Image completed - slice_00001.tif"), 50)
    assert watch.last_progress == 50


def test_reminders_are_separate_rate_limited_events_and_recovery_is_opt_in():
    watch = ActivityWatch(policy(cycles=1, reminder_seconds=60, recovery_notify=True), 0)
    assert watch.poll(10, success=True, new_bytes=0)[0]["reminder"] is False
    assert watch.poll(69, success=True, new_bytes=0) == []
    assert watch.poll(70, success=True, new_bytes=0)[0]["reminder"] is True
    assert watch.poll(71, success=True, new_bytes=3)[0]["notify"] is True


def test_lifecycle_disarms_activity_but_preserves_fault_detection_and_history_meaning():
    watch = ActivityWatch(policy(cycles=1), 0)
    fault = record("Unable to recover. Stopping acquisition.", "Error")
    assert evaluate(preset_rules("execution"), fault)["matched"]
    assert watch.record(record("Run Ended."), 10) is True
    assert watch.poll(1000, success=True, new_bytes=0) == []
    assert "success not inferred" in watch.status(1000)
    assert evaluate(preset_rules("execution"), fault)["matched"]


def test_lifecycle_disarm_can_be_disabled():
    watch = ActivityWatch(policy(cycles=1, lifecycle_disarm=False), 0)
    assert watch.record(record("Run Ended."), 10)
    assert not watch.lifecycle_paused
    assert watch.poll(20, success=True, new_bytes=0)[0]["kind"] == "silence"


@pytest.mark.parametrize(("pattern", "text", "matched"), [
    ("error", "ERROR at source", True), ("error", "terror", False),
    ("error", "error_code", False), ("error", "error-code", True),
    ("échec", "échec!", True), ("échec", "préchec", False),
    ("straße", "STRASSE!", True), ("beam blanked", "beam blanked.", True),
])
def test_unicode_whole_word_and_phrase_semantics(pattern, text, matched):
    assert matches(literal(pattern, mode="whole"), record(text)) is matched


def test_rule_case_exact_scope_component_and_disabled_modes():
    r = literal("Error", case_sensitive=True)
    assert not matches(r, record("error"))
    assert matches(r, record("Error"))
    r.update(mode="exact")
    assert not matches(r, record("Error "))
    r.update(pattern="Info", mode="contains", scope="full")
    assert matches(r, record("message", "Info"))
    r.update(scope="message")
    assert not matches(r, record("message", "Info"))
    r.update(pattern="message", component="atlas 3d")
    assert matches(r, record("message"))
    assert not matches(r, record("message", component="Imaging"))
    r["enabled"] = False
    assert not matches(r, record("message"))


@pytest.mark.parametrize("level", ["Error", "error", "FATAL", "Critical"])
def test_structured_error_levels_do_not_require_error_keyword(level):
    result = evaluate(preset_rules("engine"), record("An unexpected condition", level))
    assert result["matched"] and result["rules"] == ["engine-0"]


def test_multi_rule_match_has_one_result_and_highest_severity_channel_union():
    a = literal("recover", id="a", severity="warning", channels=["gmail"])
    b = literal("Stopping", id="b", severity="critical", channels=["telegram"])
    result = evaluate([a, b], record("Unable to recover. Stopping acquisition."))
    assert result["matched"] and result["rules"] == ["a", "b"]
    assert result["severity"] == "critical" and result["channels"] == ["gmail", "telegram"]


def test_explicit_ignore_is_auditable_and_suppresses_matching_error():
    ignore = literal("known condition", id="ignore-1", ignore=True)
    result = evaluate(preset_rules("engine") + [ignore], record("known condition", "Error"))
    assert not result["matched"] and result["ignored"] == ["ignore-1"]
    assert result["rules"] == ["engine-0"]


def test_presets_keep_eht_variants_optional_and_source_rules_independent():
    engine, execution = preset_rules("engine"), preset_rules("execution")
    assert not evaluate(engine, record("communication failed: device may not be populated"))["matched"]
    assert not evaluate(engine, record("WMAcqError WP=8 r=False", "Log"))["matched"]
    for text in ["Turning EHT OFF", "Turning SEM EHT off", "Putting FIB gun into Standby"]:
        assert not evaluate(execution, record(text))["matched"]
        candidate = next(rule for rule in execution if rule["pattern"] == text)
        candidate["enabled"] = True
        assert evaluate(execution, record(text))["matched"]
        candidate["enabled"] = False
    assert evaluate(execution, record("Cannot grab image since the beam is blanked."))["matched"]
    assert not evaluate(engine, record("Cannot grab image since the beam is blanked."))["matched"]
    engine[0]["enabled"] = False
    assert execution[0]["enabled"] is True


def test_defaults_are_safe_independent_and_use_sample_derived_thresholds():
    first, second = defaults(), defaults()
    assert not first["channels"]["gmail"]["enabled"] and not first["channels"]["telegram"]["enabled"]
    assert first["poll_seconds"] == 10
    assert not first["sources"]["engine"]["expect_activity"]
    execution = first["sources"]["execution"]
    assert execution["cycles"] * first["poll_seconds"] == 300
    assert execution["heartbeat_seconds"] == 300
    first["sources"]["execution"]["cycles"] = 1
    first["rules"]["engine"][0]["enabled"] = False
    assert second["sources"]["execution"]["cycles"] == 30
    assert second["rules"]["engine"][0]["enabled"] is True
    assert validate(second) == second


@pytest.mark.parametrize(("field", "value"), [("poll_seconds", 0), ("poll_seconds", -1),
    ("poll_seconds", 3601), ("poll_seconds", True), ("poll_seconds", float("nan")),
    ("max_events", 100.5), ("max_outbox", 10.1), ("retention_days", 1.1),
    ("mode", []), ("schema_version", 2), ("schema_version", True), ("instrument", []),
    ("close_to_tray", "false"), ("sources", []), ("rules", []), ("channels", [])])
def test_invalid_configuration_scalars_and_containers_raise_value_error(field, value):
    config = defaults()
    config[field] = value
    with pytest.raises(ValueError):
        validate(config)


@pytest.mark.parametrize(("field", "value"), [("interval", False), ("interval", -1), ("interval", 0.5),
    ("cycles", 1.5), ("cycles", 0), ("duration", 0), ("grace", -1), ("heartbeat_seconds", 0),
    ("expect_activity", "false"), ("inactivity_mode", []), ("encoding", []), ("timezone", True),
    ("timezone", "Not/AZone"), ("filename", "../atlas.log"), ("filename", ".."),
    ("filename", "atlas.log:stream"), ("filename", "atlas\n.log"), ("folder", [])])
def test_invalid_source_settings_are_rejected(field, value):
    config = defaults()
    config["sources"]["engine"][field] = value
    with pytest.raises(ValueError):
        validate(config)


@pytest.mark.parametrize(("field", "value"), [("pattern", " "), ("mode", "regex"), ("scope", "html"),
    ("severity", "vendor-error"), ("channels", ["sms"]), ("channels", "gmail"),
    ("levels", "Error"), ("case_sensitive", "false"), ("pattern", []), ("component", [])])
def test_invalid_literal_rules_are_rejected(field, value):
    config = defaults()
    config["rules"]["engine"][1][field] = value
    with pytest.raises(ValueError):
        validate(config)


def test_duplicate_rule_ids_and_missing_rule_fields_are_rejected():
    config = defaults()
    config["rules"]["engine"][1]["id"] = "engine-0"
    with pytest.raises(ValueError):
        validate(config)
    config["rules"]["engine"] = [{"name": "incomplete"}]
    with pytest.raises(ValueError):
        validate(config)


def test_secret_free_export_strips_unknown_keys_and_credential_references():
    config = defaults()
    config["password"] = "must disappear"
    config["channels"]["gmail"].update(password="must disappear", credential_ref="wincred:gmail")
    config["rules"]["engine"][0]["token"] = "must disappear"
    exported = portable_config(config)
    assert "must disappear" not in json.dumps(exported)
    assert exported["channels"]["gmail"]["credential_ref"] == ""
    assert config["channels"]["gmail"]["credential_ref"] == "wincred:gmail"


def test_credentials_are_references_only_and_channels_validate_addresses():
    for reference in ["plaintext secret", "wincred:other/path", "session:"]:
        config = defaults()
        config["channels"]["gmail"]["credential_ref"] = reference
        with pytest.raises(ValueError):
            validate(config)
    for field, value in [("sender", "bad"), ("recipients", "one@example.com"), ("port", 25)]:
        config = defaults()
        config["channels"]["gmail"][field] = value
        with pytest.raises(ValueError):
            validate(config)
    config = defaults()
    config["channels"]["telegram"]["chat_id"] = "@someone"
    with pytest.raises(ValueError):
        validate(config)


def test_source_paths_remain_separate_and_do_not_guess_vendor_spelling(tmp_path):
    config = defaults()
    config["sources"]["execution"].update(folder=str(tmp_path / "experiment"), filename="execution_log.log")
    assert str(source_path(config, "engine")) == r"C:\ProgramData\FIBIC\Atlasengine\atlasengine.log"
    assert source_path(config, "execution") == tmp_path / "experiment" / "execution_log.log"


def test_output_guards_source_file_directories_and_hardlinks(tmp_path):
    config = defaults()
    source_dir = tmp_path / "experiment"
    source_dir.mkdir()
    source = source_dir / "execution_log.log"
    source.write_bytes(b"example source")
    config["sources"]["execution"]["folder"] = str(source_dir)
    for target in [source, source_dir, source_dir / "export.json", source_dir / "nested" / "state.sqlite"]:
        with pytest.raises(ValueError):
            safe_destination(target, config)
    output = tmp_path / "exports" / "history.json"
    assert safe_destination(output, config) == output.resolve()
    linked = tmp_path / "source-hardlink.log"
    os.link(source, linked)
    with pytest.raises(ValueError):
        safe_destination(linked, config)
    assert source.read_bytes() == b"example source"


def test_output_guard_also_protects_source_with_empty_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = defaults()
    assert config["sources"]["execution"]["folder"] == ""
    with pytest.raises(ValueError):
        safe_destination(tmp_path / "execution_log.log", config)


def test_config_store_atomic_save_backup_and_corruption_recovery(tmp_path):
    store = ConfigStore(tmp_path)
    original = defaults()
    store.save(original)
    modified = copy.deepcopy(original)
    modified["job"] = "second job"
    store.save(modified)
    assert store.load()["job"] == "second job"
    assert json.loads(store.path.with_suffix(".json.previous").read_text())["job"] == ""
    store.path.write_text("invalid JSON", encoding="utf-8")
    assert store.load()["job"] == "" and store.warning
    # A crash between backup replacement and final config replacement must
    # recover the existing previous copy rather than silently defaulting.
    store.path.unlink()
    previous = original | {"job": "recover this job"}
    store.path.with_suffix(".json.previous").write_text(json.dumps(previous), encoding="utf-8")
    assert store.load()["job"] == "recover this job"


def test_all_invalid_config_copies_fall_back_to_safe_defaults(tmp_path):
    store = ConfigStore(tmp_path)
    store.path.write_text("[]", encoding="utf-8")
    store.path.with_suffix(".json.previous").write_text("{invalid", encoding="utf-8")
    loaded = store.load()
    assert loaded["channels"]["gmail"]["enabled"] is False
    assert loaded["channels"]["telegram"]["enabled"] is False
    assert store.warning

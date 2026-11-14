"""Versioned non-secret configuration and constrained state/export locations."""
from __future__ import annotations

import copy
import json
import os
import re
import socket
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def state_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "ATLASWatchdog"


def preset_rules(source: str) -> list[dict]:
    def rule(name, pattern="", enabled=False, kind="literal", levels=None):
        return dict(id=f"{source}-{len(items)}", name=name, pattern=pattern, enabled=enabled,
                    kind=kind, levels=levels or [], case_sensitive=False, mode="contains",
                    scope="message", severity="error", component="", channels=["gmail", "telegram"], ignore=False)
    items = []
    items.append(rule("Logged Error / Fatal / Critical", enabled=True, kind="level", levels=["Error", "Fatal", "Critical"]))
    for phrase in ["Turning EHT OFF", "Turning SEM EHT off", "Putting FIB gun into Standby"]:
        items.append(rule(phrase, phrase))
    if source == "engine":
        for phrase in ["WMAcqError", "Failed to assign detector"]:
            items.append(rule(phrase + " (validate operational meaning)", phrase))
    else:
        for phrase in ["The connection or the microscope does not respond.", "Unable to recover", "Stopping acquisition",
                       "Process was stopped due to an error", "Cannot grab image since the beam is blanked."]:
            items.append(rule(phrase, phrase, True))
    items.append(rule("Logged Warning", kind="level", levels=["Warning"]))
    items[-1]["severity"] = "warning"
    return items


def defaults() -> dict:
    sources = {}
    for name in ["engine", "execution"]:
        engine = name == "engine"
        sources[name] = dict(folder=r"C:\ProgramData\FIBIC\Atlasengine" if engine else "",
                             filename="atlasengine.log" if engine else "execution_log.log",
                             encoding="auto", timezone="", interval=0, expect_activity=False,
                             inactivity_mode="cycles", cycles=720 if engine else 30,
                             duration=7200 if engine else 300, grace=60,
                             heartbeat=False, heartbeat_seconds=300, progress=False, progress_seconds=900,
                             lifecycle_disarm=True, reminder_seconds=1800, recovery_notify=False)
    return dict(schema_version=1, mode="both", poll_seconds=10, instrument=socket.gethostname(), job="",
                sources=sources, rules={x: preset_rules(x) for x in sources},
                channels={"gmail": dict(enabled=False, sender="", recipients=[], port=465, credential_ref=""),
                          "telegram": dict(enabled=False, chat_id="", credential_ref="")},
                grouping_seconds=30, include_paths=False, include_context=False,
                retention_days=90, max_events=50000, max_outbox=10000,
                channel_interval_seconds=3, close_to_tray=True, local_notifications=False, geometry="")


def merge_defaults(value: dict, base=None) -> dict:
    result = copy.deepcopy(defaults() if base is None else base)
    for key, val in value.items():
        if key not in result:
            continue
        if isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = merge_defaults(val, result[key])
        else:
            result[key] = val
    return result


def source_path(config: dict, source: str) -> Path:
    s = config["sources"][source]
    return Path(s["folder"]).expanduser() / s["filename"]


def _number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not low <= value <= high:
        raise ValueError(f"{label} must be {low}–{high}.")


def validate(config: dict) -> dict:
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object.")
    for key in ["sources", "rules", "channels"]:
        if key in config and not isinstance(config[key], dict):
            raise ValueError(f"{key} must be an object.")
    c = merge_defaults(config)
    if type(c["schema_version"]) is not int or c["schema_version"] != 1:
        raise ValueError("Unsupported configuration version.")
    for key in ["instrument", "job", "geometry"]:
        if not isinstance(c[key], str):
            raise ValueError(f"{key} must be text.")
    for key in ["include_paths", "include_context", "close_to_tray", "local_notifications"]:
        if not isinstance(c[key], bool):
            raise ValueError(f"{key} must be true or false.")
    if not isinstance(c["mode"], str) or c["mode"] not in {"engine", "execution", "both"}:
        raise ValueError("Choose engine, execution, or both sources.")
    _number(c["poll_seconds"], 1, 3600, "Polling seconds")
    for source, s in c["sources"].items():
        if not isinstance(s, dict):
            raise ValueError(f"{source} source settings must be an object.")
        if not isinstance(s["folder"], str) or not isinstance(s["filename"], str) or not s["filename"] or Path(s["filename"]).name != s["filename"]:
            raise ValueError(f"{source}: enter a folder and a filename without directories.")
        if s["filename"] in {".", ".."} or any(character in s["filename"] for character in '\\/:*?"<>|\r\n\x00'):
            raise ValueError(f"{source}: filename must be a valid Windows filename.")
        _number(s["interval"], 0, 3600, f"{source} polling seconds override")
        if s["interval"] != 0:
            _number(s["interval"], 1, 3600, f"{source} polling seconds")
        for key in ["expect_activity", "heartbeat", "progress", "lifecycle_disarm", "recovery_notify"]:
            if not isinstance(s[key], bool):
                raise ValueError(f"{source} {key} must be true or false.")
        for field in ["cycles", "duration", "heartbeat_seconds", "progress_seconds"]:
            _number(s[field], 1, 604800, f"{source} {field}")
        if type(s["cycles"]) is not int:
            raise ValueError(f"{source} cycles must be a whole number.")
        for field in ["grace", "reminder_seconds"]:
            _number(s[field], 0, 604800, f"{source} {field}")
        if not isinstance(s["inactivity_mode"], str) or s["inactivity_mode"] not in {"cycles", "duration"}:
            raise ValueError("Inactivity mode must be cycles or duration.")
        if not isinstance(s["encoding"], str) or s["encoding"] not in {"auto", "utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252"}:
            raise ValueError("Unsupported source encoding.")
        if not isinstance(s["timezone"], str):
            raise ValueError("Source timezone must be text.")
        if s["timezone"]:
            try:
                ZoneInfo(s["timezone"])
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("Source timezone must be an IANA name, e.g. America/Toronto.") from exc
        if not isinstance(c["rules"][source], list):
            raise ValueError(f"{source} rules must be a list.")
        rule_ids = set()
        for r in c["rules"][source]:
            if not isinstance(r, dict):
                raise ValueError("Each rule must be an object.")
            required = {"id", "name", "pattern", "kind", "levels", "mode", "scope", "severity", "channels"}
            if not required.issubset(r):
                raise ValueError("Rule is missing required fields.")
            if any(not isinstance(r[key], str) for key in ["id", "name", "pattern", "kind", "mode", "scope", "severity"]):
                raise ValueError("Rule identifiers and matching fields must be text.")
            if not r["id"] or r["id"] in rule_ids:
                raise ValueError(f"{source} rules require distinct non-empty IDs.")
            rule_ids.add(r["id"])
            if not isinstance(r.get("component", ""), str):
                raise ValueError("Rule component must be text.")
            for key in ["enabled", "case_sensitive", "ignore"]:
                if key in r and not isinstance(r[key], bool):
                    raise ValueError(f"Rule {key} must be true or false.")
            for key in ["levels", "channels"]:
                if not isinstance(r[key], list) or any(not isinstance(value, str) for value in r[key]):
                    raise ValueError(f"Rule {key} must be a list of text values.")
            if r["kind"] not in {"literal", "level"} or r["mode"] not in {"contains", "whole", "exact"} or r["scope"] not in {"message", "full"}:
                raise ValueError("Unsupported rule type or matching mode.")
            if r["kind"] == "literal" and not r["pattern"].strip():
                raise ValueError("Literal rules cannot have empty patterns.")
            if r["kind"] == "level" and not r["levels"]:
                raise ValueError("Level rules require at least one level.")
            if r["severity"] not in {"info", "warning", "error", "critical"}:
                raise ValueError("Unsupported alert severity.")
            if set(r["channels"]) - {"gmail", "telegram"}:
                raise ValueError("Unsupported notification channel.")
        allowed_rule_keys = set(preset_rules(source)[0])
        c["rules"][source] = [{key: value for key, value in rule.items() if key in allowed_rule_keys}
                              for rule in c["rules"][source]]
    g = c["channels"]["gmail"]
    for name, channel in c["channels"].items():
        if not isinstance(channel, dict) or not isinstance(channel["enabled"], bool):
            raise ValueError(f"{name} channel settings must contain an enabled checkbox.")
        reference = channel["credential_ref"]
        if not isinstance(reference, str) or (reference and not re.fullmatch(r"(?:wincred|session):[A-Za-z0-9_.-]{1,100}", reference)):
            raise ValueError("Credentials must use an app secure-store or session reference.")
    if not isinstance(g["sender"], str) or not isinstance(g["recipients"], list) or any(not isinstance(value, str) for value in g["recipients"]):
        raise ValueError("Gmail sender must be text and recipients must be a list of addresses.")
    if type(g["port"]) is not int or g["port"] not in {465, 587}:
        raise ValueError("Gmail requires TLS on port 465 or STARTTLS on 587.")
    for address in ([g["sender"]] if g["sender"] else []) + g["recipients"]:
        if not re.fullmatch(r"[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+", address):
            raise ValueError("Enter valid email addresses without display names.")
    t = c["channels"]["telegram"]
    if not isinstance(t["chat_id"], str):
        raise ValueError("Telegram chat ID must be text containing a numeric ID.")
    if t["chat_id"] and not re.fullmatch(r"-?\d+", t["chat_id"]):
        raise ValueError("Telegram chat ID must be numeric.")
    for field, low, high in [("grouping_seconds", 0, 3600), ("retention_days", 1, 3650),
                             ("max_events", 100, 1000000), ("max_outbox", 10, 100000), ("channel_interval_seconds", 1, 3600)]:
        _number(c[field], low, high, field)
        if field in {"retention_days", "max_events", "max_outbox"} and type(c[field]) is not int:
            raise ValueError(f"{field} must be a whole number.")
    return c


def safe_destination(path: str | Path, config: dict, *, state=False) -> Path:
    p = Path(path).expanduser().resolve()
    forbidden = [Path(r"C:\ProgramData\FIBIC\Atlasengine").resolve(), Path(r"C:\ProgramData\Fibics\AtlasEngine").resolve()]
    for name in ["engine", "execution"]:
        s = config["sources"][name]
        source = source_path(config, name).resolve()
        if p == source or (p.exists() and source.exists() and os.path.samefile(p, source)):
            raise ValueError("Destination cannot overwrite a monitored source.")
        if s["folder"]:
            forbidden.append(Path(s["folder"]).expanduser().resolve())
    for folder in forbidden:
        if p == folder or folder in p.parents:
            raise ValueError("Application output must be outside source and ATLAS directories.")
    return p


class ConfigStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "config.json"
        self.warning = ""

    def load(self) -> dict:
        if not self.path.exists() and not self.path.with_suffix(".json.previous").exists():
            return defaults()
        for path in [self.path, self.path.with_suffix(".json.previous")]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                return validate(value)
            except (OSError, ValueError, TypeError, KeyError):
                self.warning = "Configuration invalid; tried previous copy. Sending starts off; review settings."
        return defaults()

    def save(self, config: dict) -> None:
        value = validate(config)
        # No secret values are accepted by the known schema. Only credential references remain.
        tmp = self.path.with_suffix(".json.tmp")
        self.directory.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if self.path.exists():
            self.path.replace(self.path.with_suffix(".json.previous"))
        tmp.replace(self.path)


def portable_config(config: dict) -> dict:
    result = validate(config)
    for channel in result["channels"].values():
        channel["credential_ref"] = ""
    return result

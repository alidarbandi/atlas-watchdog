"""Literal rule evaluation; no untrusted regular expressions."""
from __future__ import annotations
import re

SEVERITY = {"info": 0, "warning": 1, "error": 2, "critical": 3}


def matches(rule: dict, record: dict) -> bool:
    if not rule.get("enabled", True):
        return False
    if rule.get("component") and rule["component"].casefold() != record.get("component", "").casefold():
        return False
    if rule["kind"] == "level":
        return record.get("level", "").casefold() in {x.casefold() for x in rule["levels"]}
    text = record.get("raw_line", "") if rule.get("scope") == "full" else record.get("message", "")
    pattern = rule["pattern"]
    if not pattern:
        return False
    if not rule.get("case_sensitive"):
        text, pattern = text.casefold(), pattern.casefold()
    if rule["mode"] == "exact":
        return text == pattern
    if rule["mode"] == "whole":
        # Python's Unicode \w includes letters/digits/underscore. Treat boundaries consistently for phrases.
        return re.search(r"(?<!\w)" + re.escape(pattern) + r"(?!\w)", text) is not None
    return pattern in text


def evaluate(rules: list[dict], record: dict) -> dict:
    hit = [r for r in rules if matches(r, record)]
    ignores = [r for r in hit if r.get("ignore")]
    alerts = [r for r in hit if not r.get("ignore")]
    return dict(matched=bool(alerts) and not ignores, rules=[r["id"] for r in alerts],
                rule_names=[r["name"] for r in alerts], ignored=[r["id"] for r in ignores],
                severity=max((r["severity"] for r in alerts), key=lambda s: SEVERITY[s], default="info"),
                channels=sorted({c for r in alerts for c in r.get("channels", [])}))

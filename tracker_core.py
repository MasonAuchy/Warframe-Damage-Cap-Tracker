from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

DAMAGE_PATTERN = re.compile(r"Damage too high: ([\d,]+)")
MAX_HISTORY_POINTS = 50
DEFAULT_STATE: dict[str, Any] = {
    "damage_history": [0],
    "max_hit": 0,
    "hit_count": 0,
    "all_hits": 0,
    "hit_events": [],
    "session_started_at": "",
}

_SUFFIXES = (
    (1e18, "Quintillion"),
    (1e15, "Quadrillion"),
    (1e12, "Trillion"),
    (1e9, "Billion"),
    (1e6, "Million"),
)


def format_damage_value(value: float | int) -> str:
    """Format a damage number into a compact, human-readable label."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0"

    sign = "-" if numeric < 0 else ""
    absolute = abs(numeric)

    for threshold, suffix in _SUFFIXES:
        if absolute >= threshold:
            return f"{sign}{absolute / threshold:.1f} {suffix}"

    return f"{int(numeric)}"


def parse_damage_line(line: str) -> tuple[int, str] | None:
    """Extract the numeric hit value from a Warframe log line."""

    match = DAMAGE_PATTERN.search(line)
    if not match:
        return None

    raw_value = match.group(1)
    return int(raw_value.replace(",", "")), raw_value


def _coerce_int(value: Any, default: Any = 0) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_history(value: Any) -> list[int]:
    if not isinstance(value, list):
        return [0]

    history: list[int] = []
    for item in value:
        coerced = _coerce_int(item, default=None)
        if coerced is not None:
            history.append(coerced)

    return history or [0]


def _coerce_event_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    events: list[dict[str, Any]] = []
    for item in value:
        timestamp = ""
        display_timestamp = ""
        raw_value = ""
        numeric_value: int | None = None

        if isinstance(item, dict):
            timestamp = str(item.get("timestamp") or "")
            display_timestamp = str(item.get("display_timestamp") or "")
            raw_value = str(item.get("raw_value") or "")
            numeric_value = _coerce_int(item.get("value"), default=None)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            timestamp = str(item[0] or "")
            numeric_value = _coerce_int(item[1], default=None)
            if len(item) >= 3:
                raw_value = str(item[2] or "")

        if numeric_value is None:
            continue

        events.append(
            {
                "timestamp": timestamp,
                "display_timestamp": display_timestamp,
                "value": numeric_value,
                "raw_value": raw_value or str(numeric_value),
            }
        )

    return events


def normalize_state(raw_state: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize saved tracker data and keep old save files working."""

    raw_state = raw_state or {}
    damage_history = _coerce_history(raw_state.get("damage_history"))
    hit_events = _coerce_event_records(raw_state.get("hit_events"))

    if not hit_events and len(damage_history) > 1:
        hit_events = [
            {
                "timestamp": "",
                "value": value,
                "raw_value": str(value),
            }
            for value in damage_history[1:]
        ]

    event_values = [event["value"] for event in hit_events]
    values_source = event_values or damage_history

    max_hit = _coerce_int(raw_state.get("max_hit"), default=max(values_source, default=0))
    all_hits = _coerce_int(raw_state.get("all_hits"), default=sum(event_values) if event_values else sum(damage_history))

    if "hit_count" in raw_state:
        hit_count = _coerce_int(raw_state.get("hit_count"), default=len(hit_events))
    elif "total_hits_above_cap" in raw_state:
        hit_count = max(0, _coerce_int(raw_state.get("total_hits_above_cap"), default=1) - 1)
    else:
        hit_count = len(hit_events)

    session_started_at = raw_state.get("session_started_at")
    if not session_started_at:
        session_started_at = datetime.now().isoformat(timespec="seconds")
    else:
        session_started_at = str(session_started_at)

    return {
        "damage_history": damage_history,
        "max_hit": max_hit,
        "hit_count": hit_count,
        "total_hits_above_cap": hit_count + 1,
        "all_hits": all_hits,
        "hit_events": hit_events,
        "session_started_at": session_started_at,
    }


def load_saved_state(path: Path) -> dict[str, Any]:
    """Load persisted tracker state from disk with safe fallbacks."""

    if not path.exists():
        return normalize_state(DEFAULT_STATE)

    try:
        raw_state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return normalize_state(DEFAULT_STATE)

    if not isinstance(raw_state, dict):
        return normalize_state(DEFAULT_STATE)

    return normalize_state(raw_state)


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Persist tracker state to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)

    normalized = normalize_state(state)
    state_to_write = {
        "damage_history": normalized["damage_history"],
        "max_hit": normalized["max_hit"],
        "hit_count": normalized["hit_count"],
        "total_hits_above_cap": normalized["total_hits_above_cap"],
        "all_hits": normalized["all_hits"],
        "hit_events": normalized["hit_events"],
        "session_started_at": normalized["session_started_at"],
    }

    path.write_text(json.dumps(state_to_write, indent=2), encoding="utf-8")

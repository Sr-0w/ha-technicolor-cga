"""Pure helpers that turn the gateway's JSON into numbers and log events.

Nothing here imports Home Assistant, so it can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
import html
import re
from typing import Any

# DOCSIS event priorities, as reported in the "level" field of LogTbl.
LEVEL_NAMES = {
    1: "emergency",
    2: "alert",
    3: "critical",
    4: "error",
    5: "warning",
    6: "notice",
    7: "information",
    8: "debug",
}

# Event categories, also used as the event entity's event types.
CATEGORY_DISCONNECTION = "disconnection"
CATEGORY_REBOOT = "reboot"
CATEGORY_T3_TIMEOUT = "t3_timeout"
CATEGORY_T4_TIMEOUT = "t4_timeout"
CATEGORY_SYNC_LOSS = "sync_loss"
CATEGORY_DHCP_FAILURE = "dhcp_failure"
CATEGORY_OTHER = "other"
CATEGORIES = (
    CATEGORY_DISCONNECTION,
    CATEGORY_REBOOT,
    CATEGORY_T3_TIMEOUT,
    CATEGORY_T4_TIMEOUT,
    CATEGORY_SYNC_LOSS,
    CATEGORY_DHCP_FAILURE,
    CATEGORY_OTHER,
)

# Order matters: the first matching rule wins.
_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A (re-)registration marks the end of an outage: one per lost connection.
    (CATEGORY_DISCONNECTION, re.compile(r"^CM State is operational", re.I)),
    (CATEGORY_REBOOT, re.compile(r"(Cable Modem Reboot|Resetting the cable modem)", re.I)),
    (CATEGORY_T3_TIMEOUT, re.compile(r"T3 time[- ]?out", re.I)),
    (CATEGORY_T4_TIMEOUT, re.compile(r"T4 time[- ]?out", re.I)),
    (
        CATEGORY_SYNC_LOSS,
        re.compile(r"(SYNC Timing Synchronization failure|Lost MDD Timeout|Loss of Sync)", re.I),
    ),
    (CATEGORY_DHCP_FAILURE, re.compile(r"DHCP FAILED", re.I)),
)

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def number(value: Any) -> float | None:
    """Read '5.6 dBmV', '40.2 dB' or '14009' as a float; None when absent."""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or value.strip().upper() in ("", "NA", "N/A"):
        return None
    match = _NUMBER.search(value)
    return float(match.group()) if match else None


@dataclass(frozen=True)
class LogEntry:
    """One line of the gateway's DOCSIS event log."""

    signature: str
    time: datetime | None
    event_id: str
    level: int | None
    text: str
    category: str

    @property
    def level_name(self) -> str | None:
        """Return the DOCSIS priority name."""
        return LEVEL_NAMES.get(self.level) if self.level is not None else None


def clean_text(text: str) -> str:
    """Drop the trailing ';CM-MAC=...;CMTS-MAC=...' noise the gateway appends."""
    return re.split(r";?;?CM-MAC=", text, maxsplit=1)[0].strip(" ;")


def categorize(text: str) -> str:
    """Return the category of a log message."""
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            return category
    return CATEGORY_OTHER


def parse_time(value: Any, tz: tzinfo) -> datetime | None:
    """Parse 'Thu Nov  5 21:39:40 2026' in the gateway's local time.

    Entries written before the clock is set are dated 1970: they get None.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(" ".join(value.split()), "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
    if parsed.year < 2000:
        return None
    return parsed.replace(tzinfo=tz)


def parse_log(rows: Any, tz: tzinfo) -> list[LogEntry]:
    """Turn LogTbl rows into entries, oldest first as the gateway lists them."""
    if not isinstance(rows, list):
        return []
    entries: list[LogEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_time = str(row.get("time", "")).strip()
        raw_text = str(row.get("text", "")).strip()
        event_id = str(row.get("id", "")).strip()
        try:
            level: int | None = int(str(row.get("level", "")).strip())
        except ValueError:
            level = None
        text = clean_text(raw_text)
        entries.append(
            LogEntry(
                # Neither __id (a table position) nor the time (1970 before
                # the clock is set) is unique on its own; together with the
                # message they are.
                signature=f"{raw_time}|{event_id}|{raw_text}",
                time=parse_time(raw_time, tz),
                event_id=event_id,
                level=level,
                text=text,
                category=categorize(text),
            )
        )
    return entries


# "[88000205]: 204,2026-11-06 10:47:44 Radio=wl0 Interface Reset ,Link is Up."
# The gateway folds repeats of one message into a row: id, count, first time.
_GATEWAY_LOG = re.compile(
    r"^\[(?P<id>[^\]]+)\]:\s*(?P<count>\d+),(?P<first>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*(?P<text>.*)$",
    re.S,
)
WIFI_RADIO_RESET = "88000205"
GATEWAY_LOG_LIMIT = 20


def parse_local_time(value: Any, tz: tzinfo) -> datetime | None:
    """Parse '2026-11-06 13:40:17' in the gateway's local time."""
    try:
        parsed = datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return None if parsed.year < 2000 else parsed.replace(tzinfo=tz)


def _gateway_rows(rows: Any, tz: tzinfo, time_key: str, text_key: str, level_key: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        raw = html.unescape(str(row.get(text_key, ""))).strip()
        match = _GATEWAY_LOG.match(raw)
        last = parse_local_time(row.get(time_key), tz)
        first = parse_local_time(match["first"], tz) if match else None
        out.append(
            {
                "time": last.isoformat() if last else None,
                "first": first.isoformat() if first else None,
                "count": int(match["count"]) if match else None,
                "id": match["id"] if match else None,
                "level": str(row.get(level_key) or "").strip() or None if level_key else None,
                "text": " ".join((match["text"] if match else raw).split()),
            }
        )
    return out


def parse_gateway_logs(report: Any, remotelog: Any, tz: tzinfo) -> dict[str, list[dict[str, Any]]]:
    """The Wi-Fi, system and security logs of the gateway, newest first."""
    report = report if isinstance(report, dict) else {}
    remotelog = remotelog if isinstance(remotelog, dict) else {}
    logs = {
        "wifi": _gateway_rows(report.get("WiFiLogTbl"), tz, "Time", "Des", None),
        "security": _gateway_rows(report.get("LogTbl"), tz, "time", "Des", "Type"),
        "system": _gateway_rows(remotelog.get("SysTbl"), tz, "date", "msg", "type")
        + _gateway_rows(remotelog.get("eRouterTbl"), tz, "date", "msg", "type"),
    }
    for key, entries in logs.items():
        entries.sort(key=lambda e: e["time"] or "", reverse=True)
        logs[key] = entries[:GATEWAY_LOG_LIMIT]
    return logs


def _channel_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("LockStatus", "Locked")).lower() == "locked"
    ]


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "avg": None, "max": None}
    return {
        "min": min(values),
        "avg": round(sum(values) / len(values), 2),
        "max": max(values),
    }


def summarize_channels(modem: dict[str, Any]) -> dict[str, Any]:
    """Aggregate per-channel tables into the handful of values worth graphing."""
    ds = _channel_rows(modem.get("DSTbl"))
    ofdm = _channel_rows(modem.get("exDSTbl"))
    us = _channel_rows(modem.get("USTbl"))
    ofdma = _channel_rows(modem.get("exUSTbl"))

    def values(rows: list[dict[str, Any]], key: str) -> list[float]:
        return [v for row in rows if (v := number(row.get(key))) is not None]

    corrected = values(_all_rows(modem.get("ErrTbl")), "Correcteds")
    uncorrectable = values(_all_rows(modem.get("ErrTbl")), "Uncorrectables")
    if not corrected:  # Some firmwares only report errors in DSTbl.
        corrected = values(ds, "Correcteds")
        uncorrectable = values(ds, "Uncorrectables")

    return {
        "ds_power": _stats(values(ds, "PowerLevel")),
        "ds_snr": _stats(values(ds, "SNRLevel")),
        "ofdm_power": _stats(values(ofdm, "PowerLevel")),
        "ofdm_snr": _stats(values(ofdm, "SNRLevel")),
        "us_power": _stats(values(us, "PowerLevel") + values(ofdma, "PowerLevel")),
        "ds_locked": len(ds) + len(ofdm),
        "us_locked": len(us) + len(ofdma),
        "corrected": int(sum(corrected)) if corrected else None,
        "uncorrectable": int(sum(uncorrectable)) if uncorrectable else None,
        "channels": {
            "downstream": [_channel_summary(r) for r in ds + ofdm],
            "upstream": [_channel_summary(r) for r in us + ofdma],
        },
    }


def _all_rows(rows: Any) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _channel_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("ChannelID"),
        "type": row.get("ChannelType"),
        "frequency": row.get("CentralFrequency") or row.get("Frequency"),
        "power": number(row.get("PowerLevel")),
        "snr": number(row.get("SNRLevel")),
        "modulation": row.get("Modulation") or row.get("FFT"),
    }

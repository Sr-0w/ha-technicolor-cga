"""Diagnostics for the Technicolor CGA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import GatewayConfigEntry

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    "SerialNumber",
    "CMMACAddress",
    "configuration_url",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GatewayConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without credentials or identifiers."""
    data = entry.runtime_data.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "system": async_redact_data(data.system, TO_REDACT),
        "summary": data.summary,
        "counters": data.counters,
        "session_busy": data.session_busy,
        "log": [
            {
                "time": e.time.isoformat() if e.time else None,
                "level": e.level_name,
                "category": e.category,
                "text": e.text,
            }
            for e in data.log
        ],
    }

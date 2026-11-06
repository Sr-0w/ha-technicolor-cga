"""An event entity firing for every new line of the gateway's event log."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GatewayConfigEntry
from .const import SIGNAL_LOG_EVENT
from .entity import GatewayEntity
from .parser import CATEGORIES, LogEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event entity."""
    async_add_entities([GatewayLogEvent(entry.runtime_data)])


class GatewayLogEvent(GatewayEntity, EventEntity):
    """Fire one event per new DOCSIS log line, typed by its category."""

    _attr_event_types = list(CATEGORIES)
    _attr_translation_key = "docsis_log"

    def __init__(self, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "docsis_log")

    async def async_added_to_hass(self) -> None:
        """Listen for new log lines."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_LOG_EVENT.format(self.coordinator.config_entry.entry_id),
                self._handle_log_entry,
            )
        )
        for entry in self.coordinator.take_undelivered_log_entries():
            self._handle_log_entry(entry)

    @callback
    def _handle_log_entry(self, entry: LogEntry) -> None:
        self._trigger_event(
            entry.category,
            {
                "message": entry.text,
                "level": entry.level_name,
                "event_id": entry.event_id,
                "logged_at": entry.time.isoformat() if entry.time else None,
            },
        )
        self.async_write_ha_state()

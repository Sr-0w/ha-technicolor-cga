"""Binary sensors of the Technicolor CGA integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GatewayConfigEntry
from .entity import GatewayEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities([CableConnection(coordinator), WebSessionBusy(coordinator)])


class CableConnection(GatewayEntity, BinarySensorEntity):
    """On while the cable modem is registered with the network."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "cable_connection"

    def __init__(self, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "cable_connection")

    @property
    def is_on(self) -> bool | None:
        """Return true when DOCSIS is operational."""
        status = self.coordinator.data.system.get("CMStatus")
        return None if not status or status == "NA" else status.upper() == "OPERATIONAL"


class WebSessionBusy(GatewayEntity, BinarySensorEntity):
    """On while polling is paused because the web interface holds the session."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "web_session_busy"

    def __init__(self, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "web_session_busy")

    @property
    def is_on(self) -> bool:
        """Return true while paused."""
        return self.coordinator.data.session_busy

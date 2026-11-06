"""Base entity for the Technicolor CGA integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GatewayCoordinator


class GatewayEntity(CoordinatorEntity[GatewayCoordinator]):
    """An entity of the gateway device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GatewayCoordinator, key: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        system = coordinator.data.system
        mac = str(system.get("CMMACAddress") or "").lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            name="Modem",
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            manufacturer=system.get("Manufacturer") or "Technicolor",
            model=system.get("ModelName"),
            hw_version=system.get("HardwareVersion"),
            sw_version=system.get("SoftwareVersion"),
            serial_number=system.get("SerialNumber"),
            configuration_url=coordinator.client.host,
        )

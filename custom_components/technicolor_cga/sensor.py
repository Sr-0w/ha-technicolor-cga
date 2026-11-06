"""Sensors of the Technicolor CGA integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GatewayConfigEntry
from .coordinator import COUNTER_REBOOTS, GatewayData
from .entity import GatewayEntity
from .parser import (
    CATEGORY_DHCP_FAILURE,
    CATEGORY_DISCONNECTION,
    CATEGORY_SYNC_LOSS,
    CATEGORY_T3_TIMEOUT,
    CATEGORY_T4_TIMEOUT,
    number,
)

DBMV = "dBmV"
DB = "dB"
RECENT_LOG_LINES = 15


@dataclass(frozen=True, kw_only=True)
class GatewaySensorDescription(SensorEntityDescription):
    """Describe a gateway sensor."""

    value_fn: Callable[[GatewayData], Any]
    attrs_fn: Callable[[GatewayData], dict[str, Any]] | None = None


def _stat(group: str, kind: str) -> Callable[[GatewayData], Any]:
    return lambda data: data.summary[group][kind]


def _signal(key: str, group: str, kind: str, unit: str, **kwargs: Any) -> GatewaySensorDescription:
    return GatewaySensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_stat(group, kind),
        **kwargs,
    )


def _counter(key: str, counter: str) -> GatewaySensorDescription:
    return GatewaySensorDescription(
        key=key,
        translation_key=key,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.counters[counter],
    )


def _memory_used(data: GatewayData) -> float | None:
    free, total = number(data.system.get("MemFree")), number(data.system.get("MemTotal"))
    if free is None or not total:
        return None
    return round(100 * (total - free) / total, 1)


def _last_event(data: GatewayData) -> Any:
    # The table is in logging order; the clock can jump back while it is being
    # set, so the newest line is the last dated one, not the latest date.
    dated = [entry for entry in data.log if entry.time is not None]
    return dated[-1].time if dated else None


def _recent_log(data: GatewayData) -> dict[str, Any]:
    dated = [entry for entry in reversed(data.log) if entry.time is not None]
    lines = [
        {
            "time": entry.time.isoformat(),
            "level": entry.level_name,
            "category": entry.category,
            "text": entry.text,
        }
        for entry in dated[:RECENT_LOG_LINES]
    ]
    return {"message": lines[0]["text"] if lines else None, "recent": lines}


SENSORS: tuple[GatewaySensorDescription, ...] = (
    GatewaySensorDescription(
        key="docsis_status",
        translation_key="docsis_status",
        value_fn=lambda data: data.system.get("CMStatus"),
    ),
    _signal(
        "downstream_power",
        "ds_power",
        "avg",
        DBMV,
        attrs_fn=lambda data: {"channels": data.summary["channels"]["downstream"]},
    ),
    _signal("downstream_power_min", "ds_power", "min", DBMV),
    _signal("downstream_power_max", "ds_power", "max", DBMV),
    _signal("downstream_snr", "ds_snr", "avg", DB),
    _signal("downstream_snr_min", "ds_snr", "min", DB),
    _signal("ofdm_power", "ofdm_power", "avg", DBMV),
    _signal("ofdm_snr", "ofdm_snr", "avg", DB),
    _signal(
        "upstream_power",
        "us_power",
        "avg",
        DBMV,
        attrs_fn=lambda data: {"channels": data.summary["channels"]["upstream"]},
    ),
    _signal("upstream_power_max", "us_power", "max", DBMV),
    GatewaySensorDescription(
        key="downstream_channels",
        translation_key="downstream_channels",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.summary["ds_locked"],
    ),
    GatewaySensorDescription(
        key="upstream_channels",
        translation_key="upstream_channels",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.summary["us_locked"],
    ),
    GatewaySensorDescription(
        key="corrected_codewords",
        translation_key="corrected_codewords",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.summary["corrected"],
    ),
    GatewaySensorDescription(
        key="uncorrectable_codewords",
        translation_key="uncorrectable_codewords",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.summary["uncorrectable"],
    ),
    _counter("disconnections", CATEGORY_DISCONNECTION),
    _counter("reboots", COUNTER_REBOOTS),
    _counter("t3_timeouts", CATEGORY_T3_TIMEOUT),
    _counter("t4_timeouts", CATEGORY_T4_TIMEOUT),
    _counter("sync_losses", CATEGORY_SYNC_LOSS),
    _counter("dhcp_failures", CATEGORY_DHCP_FAILURE),
    GatewaySensorDescription(
        key="last_log_event",
        translation_key="last_log_event",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_event,
        attrs_fn=_recent_log,
    ),
    GatewaySensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_boot,
    ),
    GatewaySensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: number(data.system.get("CPUUsage")),
    ),
    GatewaySensorDescription(
        key="memory_usage",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_memory_used,
    ),
    GatewaySensorDescription(
        key="last_reboot_reason",
        translation_key="last_reboot_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.system.get("LastRebootReason"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(GatewaySensor(coordinator, description) for description in SENSORS)


class GatewaySensor(GatewayEntity, SensorEntity):
    """A sensor of the gateway."""

    entity_description: GatewaySensorDescription
    # Channel lists and recent log lines are for the UI, not for the database.
    _unrecorded_attributes = frozenset({"channels", "recent", "message"})

    def __init__(self, coordinator, description: GatewaySensorDescription) -> None:
        """Initialize."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)

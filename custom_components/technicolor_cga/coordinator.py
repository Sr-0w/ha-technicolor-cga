"""Poll the gateway, and turn its event log into persistent counters."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AuthenticationError,
    GatewayClient,
    GatewayError,
    LockedOutError,
    SessionBusyError,
)
from .const import (
    BUSY_BACKOFF_MAX,
    BUSY_BACKOFF_START,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SEEN_LOG_LIMIT,
    SIGNAL_LOG_EVENT,
    STORAGE_VERSION,
)
from .parser import CATEGORIES, LogEntry, number, parse_log, summarize_channels

_LOGGER = logging.getLogger(__name__)

COUNTER_REBOOTS = "reboots"


@dataclass(frozen=True)
class GatewayData:
    """One snapshot of the gateway, as the entities read it."""

    system: dict[str, Any]
    summary: dict[str, Any]
    log: list[LogEntry]
    last_boot: datetime | None
    counters: dict[str, int]
    session_busy: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class GatewayCoordinator(DataUpdateCoordinator[GatewayData]):
    """Read the gateway on a fixed beat and keep the log counters."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: GatewayClient) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._counters: dict[str, int] = {c: 0 for c in (*CATEGORIES, COUNTER_REBOOTS)}
        self._seen: list[str] = []
        self._baselined = False
        self._last_uptime: float | None = None
        self._last_boot: datetime | None = None
        self._pause_until = 0.0
        self._backoff = BUSY_BACKOFF_START
        self._session_open = False
        self._device_info: dict[str, Any] = {}
        # New log lines found before the event entity listens (the first
        # refresh runs before platforms are set up) wait here.
        self._log_listener_ready = False
        self._undelivered: list[LogEntry] = []

    async def async_load_state(self) -> None:
        """Restore counters and the already counted log lines."""
        stored = await self._store.async_load() or {}
        for key, value in (stored.get("counters") or {}).items():
            if key in self._counters and isinstance(value, int):
                self._counters[key] = value
        self._seen = [s for s in stored.get("seen", []) if isinstance(s, str)]
        self._baselined = bool(stored.get("baselined"))
        self._last_uptime = stored.get("last_uptime")
        self._device_info = stored.get("device") or {}
        if stored.get("session_open"):
            self.client.take_over_once = True

    def _save_state(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "counters": self._counters,
                "seen": self._seen[-SEEN_LOG_LIMIT:],
                "baselined": self._baselined,
                "last_uptime": self._last_uptime,
                "session_open": self._session_open,
                "device": self._device_info,
            },
            5,
        )

    async def async_logout(self) -> None:
        """Close the gateway session and remember that it is closed."""
        await self.client.async_logout()
        self._session_open = False
        self._save_state()
        await self._store.async_save(
            {
                "counters": self._counters,
                "seen": self._seen[-SEEN_LOG_LIMIT:],
                "baselined": self._baselined,
                "last_uptime": self._last_uptime,
                "session_open": False,
                "device": self._device_info,
            }
        )

    def _pause(self, seconds: float, why: str) -> GatewayData:
        self._pause_until = time.monotonic() + seconds
        _LOGGER.info("Pausing gateway polling for %d s: %s", seconds, why)
        if self.data is None:
            # Failing the setup would make Home Assistant retry within seconds,
            # and every refused login may count against the account. Start
            # paused instead, with the device as it was last seen.
            return GatewayData(
                system=dict(self._device_info),
                summary=summarize_channels({}),
                log=[],
                last_boot=None,
                counters=dict(self._counters),
                session_busy=True,
            )
        return replace(self.data, session_busy=True)

    async def _async_update_data(self) -> GatewayData:
        if self.data is not None and time.monotonic() < self._pause_until:
            return self.data
        try:
            raw = await self.client.async_get_data()
        except SessionBusyError:
            data = self._pause(self._backoff, "the web interface is logged in")
            self._backoff = min(self._backoff * 2, BUSY_BACKOFF_MAX)
            return data
        except LockedOutError as err:
            return self._pause((err.wait or 300) + 30, str(err))
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GatewayError as err:
            raise UpdateFailed(str(err)) from err
        self._backoff = BUSY_BACKOFF_START

        system, modem = raw["system"], raw["modem"]
        self._session_open = self.client.authenticated
        self._device_info = {
            key: system.get(key)
            for key in (
                "ModelName",
                "Manufacturer",
                "HardwareVersion",
                "SoftwareVersion",
                "SerialNumber",
                "CMMACAddress",
            )
        }
        log = parse_log(modem.get("LogTbl"), dt_util.get_default_time_zone())
        self._count_new_log_entries(log)
        self._track_uptime(number(system.get("UpTime")))
        self._save_state()
        return GatewayData(
            system=system,
            summary=summarize_channels(modem),
            log=log,
            last_boot=self._last_boot,
            counters=dict(self._counters),
        )

    def _count_new_log_entries(self, log: list[LogEntry]) -> None:
        seen = set(self._seen)
        new = [entry for entry in log if entry.signature not in seen]
        self._seen.extend(entry.signature for entry in new)
        del self._seen[:-SEEN_LOG_LIMIT]
        if not self._baselined:
            # What the log already held at setup happened before anybody was
            # counting: it is history, not new events.
            self._baselined = True
            return
        for entry in new:
            self._counters[entry.category] += 1
            if self._log_listener_ready:
                async_dispatcher_send(
                    self.hass, SIGNAL_LOG_EVENT.format(self.config_entry.entry_id), entry
                )
            else:
                self._undelivered.append(entry)

    def take_undelivered_log_entries(self) -> list[LogEntry]:
        """Mark the event entity as listening, and hand it what it missed."""
        self._log_listener_ready = True
        entries, self._undelivered = self._undelivered, []
        return entries

    def _track_uptime(self, uptime: float | None) -> None:
        if uptime is None:
            return
        if self._last_uptime is not None and uptime + 120 < self._last_uptime:
            self._counters[COUNTER_REBOOTS] += 1
        self._last_uptime = uptime
        boot = (dt_util.utcnow() - timedelta(seconds=uptime)).replace(second=0, microsecond=0)
        # The uptime and the clock tick separately: keep the boot time stable
        # unless it really moved.
        if self._last_boot is None or abs((boot - self._last_boot).total_seconds()) > 120:
            self._last_boot = boot

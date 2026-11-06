"""The Technicolor CGA cable gateway integration."""

from __future__ import annotations

from aiohttp import CookieJar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GatewayClient
from .const import CONF_TAKE_OVER_SESSION
from .coordinator import GatewayCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]

type GatewayConfigEntry = ConfigEntry[GatewayCoordinator]


def create_client(hass: HomeAssistant, data: dict, take_over: bool) -> GatewayClient:
    """Build a client with its own cookie jar (the gateway is addressed by IP)."""
    session = async_create_clientsession(hass, cookie_jar=CookieJar(unsafe=True))
    return GatewayClient(
        session, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD], take_over
    )


async def async_setup_entry(hass: HomeAssistant, entry: GatewayConfigEntry) -> bool:
    """Set up the gateway from a config entry."""
    client = create_client(
        hass, dict(entry.data), entry.options.get(CONF_TAKE_OVER_SESSION, False)
    )
    coordinator = GatewayCoordinator(hass, entry, client)
    await coordinator.async_load_state()
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.async_close()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def _logout_on_stop(_event: Event) -> None:
        # Entries are not unloaded on shutdown: free the web session anyway.
        await coordinator.async_logout()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _logout_on_stop)
    )
    return True


async def _async_options_updated(hass: HomeAssistant, entry: GatewayConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GatewayConfigEntry) -> bool:
    """Unload, and free the gateway's single web session."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_logout()
        await entry.runtime_data.client.async_close()
    return unloaded

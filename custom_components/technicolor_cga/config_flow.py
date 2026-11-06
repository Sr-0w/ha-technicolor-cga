"""Config flow for the Technicolor CGA integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import ClientSession, CookieJar
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import (
    AuthenticationError,
    GatewayClient,
    GatewayError,
    LockedOutError,
    SessionBusyError,
    normalize_host,
)
from .const import (
    CONF_TAKE_OVER_SESSION,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


async def _validate(data: Mapping[str, Any], take_over: bool) -> dict[str, Any]:
    """Log in once, read the gateway, and free the session again."""
    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        client = GatewayClient(
            session, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD], take_over
        )
        try:
            result = await client.async_get_data()
        finally:
            await client.async_logout()
    return result["system"]


def _errors_for(err: Exception) -> dict[str, str]:
    if isinstance(err, SessionBusyError):
        return {"base": "session_busy"}
    if isinstance(err, LockedOutError):
        return {"base": "locked_out"}
    if isinstance(err, AuthenticationError):
        return {"base": "invalid_auth"}
    if isinstance(err, ValueError):
        return {CONF_HOST: "invalid_host"}
    return {"base": "cannot_connect"}


class TechnicolorCgaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the gateway's address and login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            take_over = user_input.pop(CONF_TAKE_OVER_SESSION, False)
            try:
                user_input[CONF_HOST] = normalize_host(user_input[CONF_HOST])
                system = await _validate(user_input, take_over)
            except (GatewayError, ValueError) as err:
                errors = _errors_for(err)
            else:
                identifier = str(system.get("CMMACAddress") or system.get("SerialNumber"))
                await self.async_set_unique_id(identifier.lower())
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                return self.async_create_entry(
                    title=system.get("ModelName") or "Technicolor CGA",
                    data=user_input,
                    options={
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_TAKE_OVER_SESSION: take_over,
                    },
                )
        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
                    vol.Required(
                        CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)
                    ): str,
                    vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
                    vol.Optional(CONF_TAKE_OVER_SESSION, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                await _validate(data, entry.options.get(CONF_TAKE_OVER_SESSION, False))
            except (GatewayError, ValueError) as err:
                errors = _errors_for(err)
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return TechnicolorCgaOptionsFlow()


class TechnicolorCgaOptionsFlow(OptionsFlow):
    """Polling interval and session behaviour."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    ),
                    vol.Required(
                        CONF_TAKE_OVER_SESSION,
                        default=options.get(CONF_TAKE_OVER_SESSION, False),
                    ): bool,
                }
            ),
        )

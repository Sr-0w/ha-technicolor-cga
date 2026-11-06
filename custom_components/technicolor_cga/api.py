"""Client for the local JSON API of Technicolor CGA cable gateways.

The gateway keeps a single web session per user. Logging in while someone
else (the web interface, or a session this client lost track of) is logged in
returns MSG_LOGIN_150; the web UI then offers to end that session, which it
does by adding ``logout=true`` to the salt request. This client only does that
when asked to, so opening the web interface pauses polling instead of being
kicked out every minute.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

import aiohttp
from yarl import URL

_LOGGER = logging.getLogger(__name__)

SYSTEM_FIELDS = (
    "CMStatus",
    "ModelName",
    "Manufacturer",
    "SerialNumber",
    "CMMACAddress",
    "HardwareVersion",
    "SoftwareVersion",
    "UpTime",
    "LastRebootReason",
    "CPUUsage",
    "MemFree",
    "MemTotal",
    "LocalTime",
)
MODEM_FIELDS = ("DSTbl", "exDSTbl", "USTbl", "exUSTbl", "ErrTbl", "LogTbl")

MSG_SESSION_BUSY = "MSG_LOGIN_150"


class GatewayError(Exception):
    """The gateway could not be read."""


class AuthenticationError(GatewayError):
    """The gateway rejected the credentials."""


class SessionBusyError(GatewayError):
    """Another session (usually the web interface) holds the gateway."""


class LockedOutError(GatewayError):
    """Too many failed logins: the gateway refuses logins for a while."""

    def __init__(self, wait: int | None) -> None:
        super().__init__(f"Login locked by the gateway for {wait} s")
        self.wait = wait


def normalize_host(host: str) -> str:
    """Accept '192.168.0.1' or 'http://192.168.0.1', nothing with a path."""
    host = host.strip()
    url = URL(host if "://" in host else f"http://{host}")
    if url.scheme not in ("http", "https") or not url.host or url.path not in ("", "/"):
        raise ValueError("invalid_host")
    return str(url.origin())


def derive_password(password: str, salt: str, web_salt: str) -> str:
    """Reproduce the web UI's two-step SJCL PBKDF2-HMAC-SHA256 hash."""
    first = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 1000, 16).hex()
    return hashlib.pbkdf2_hmac("sha256", first.encode(), web_salt.encode(), 1000, 16).hex()


class GatewayClient:
    """Keep one authenticated session and read the gateway with it."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        take_over_session: bool = False,
    ) -> None:
        self.host = normalize_host(host)
        self._session = session
        self._username = username
        self._password = password
        self.take_over_session = take_over_session
        # Set when a session this integration opened was never closed (a
        # crash): ending it cannot kick a person out of the web interface.
        self.take_over_once = False
        self._authenticated = False
        self._lock = asyncio.Lock()

    def _headers(self) -> dict[str, str]:
        auth = self._session.cookie_jar.filter_cookies(URL(self.host)).get("auth")
        return {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": auth.value if auth else "",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self.host}/",
        }

    async def _request(
        self, method: str, path: str, form: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            async with self._session.request(
                method,
                f"{self.host}/api/v1/{path}",
                data=form,
                headers=self._headers(),
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                payload = await response.json(content_type=None)
                status = response.status
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise GatewayError(f"No usable answer from {self.host}: {err!r}") from err
        if not isinstance(payload, dict):
            raise GatewayError("Unexpected answer from the gateway")
        if status == 401 and path == "session/login":
            raise LockedOutError(_failed_attempts(payload))
        if status in (401, 403):
            raise AuthenticationError("Session expired")
        if status != 200:
            raise GatewayError(f"Gateway answered HTTP {status}")
        return payload

    async def _login(self) -> None:
        self._authenticated = False
        salt_form = {"username": self._username, "password": "seeksalthash"}
        if self.take_over_session or self.take_over_once:
            salt_form["logout"] = "true"
        self.take_over_once = False
        challenge = await self._request("POST", "session/login", salt_form)
        if challenge.get("error") != "ok":
            _raise_login_error(challenge)
        salt, web_salt = challenge.get("salt"), challenge.get("saltwebui")
        if salt == "none":
            password = self._password
        elif isinstance(salt, str) and isinstance(web_salt, str):
            password = await asyncio.to_thread(
                derive_password, self._password, salt, web_salt
            )
        else:
            raise GatewayError("Unsupported login challenge")
        result = await self._request(
            "POST", "session/login", {"username": self._username, "password": password}
        )
        if result.get("error") != "ok":
            _raise_login_error(result)
        # The web UI reads the menu right after logging in; without it the
        # gateway answers data requests with errors.
        await self._request("GET", "session/menu")
        self._authenticated = True

    async def _read(self, path: str) -> dict[str, Any]:
        payload = await self._request("GET", path)
        data = payload.get("data")
        if payload.get("error") != "ok" or not isinstance(data, dict):
            # An expired session answers with an error rather than a 401.
            raise AuthenticationError(f"Gateway refused {path}")
        return data

    async def async_get_data(self) -> dict[str, Any]:
        """Return {'system': ..., 'modem': ...}, logging in again once if needed."""
        async with self._lock:
            for attempt in range(2):
                if not self._authenticated:
                    await self._login()
                try:
                    system = await self._read("system/" + ",".join(SYSTEM_FIELDS))
                    modem = await self._read("modem/" + ",".join(MODEM_FIELDS))
                except AuthenticationError:
                    self._authenticated = False
                    if attempt:
                        raise GatewayError("Session lost twice in a row") from None
                    continue
                return {"system": system, "modem": modem}
        raise GatewayError("unreachable")

    @property
    def authenticated(self) -> bool:
        """Return whether a session is currently open."""
        return self._authenticated

    async def async_logout(self) -> None:
        """End the session so the web interface is free right away."""
        async with self._lock:
            if not self._authenticated:
                return
            try:
                await self._request("POST", "session/logout", {})
            except GatewayError as err:
                _LOGGER.debug("Logout failed: %s", err)
            self._authenticated = False

    async def async_close(self) -> None:
        """Close the HTTP session this client owns."""
        await self._session.close()


def _failed_attempts(payload: dict[str, Any]) -> int | None:
    data = payload.get("data")
    value = data.get("failedAttempts") if isinstance(data, dict) else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _raise_login_error(payload: dict[str, Any]) -> None:
    if payload.get("message") == MSG_SESSION_BUSY:
        raise SessionBusyError("Another session is logged in")
    raise AuthenticationError(str(payload.get("message") or "Login rejected"))

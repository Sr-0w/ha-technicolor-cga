"""Constants for the Technicolor CGA integration."""

DOMAIN = "technicolor_cga"

CONF_TAKE_OVER_SESSION = "take_over_session"

DEFAULT_HOST = "192.168.0.1"
DEFAULT_USERNAME = "user"
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 3600

# When the web interface holds the session, wait before trying again, and
# wait longer each time: every refused login may count as a failed attempt.
BUSY_BACKOFF_START = 120
BUSY_BACKOFF_MAX = 900

STORAGE_VERSION = 1
SEEN_LOG_LIMIT = 500

SIGNAL_LOG_EVENT = f"{DOMAIN}_log_event_{{}}"

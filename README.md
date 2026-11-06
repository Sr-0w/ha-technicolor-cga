# Technicolor CGA cable gateway for Home Assistant

A local, read-only Home Assistant integration for Technicolor (Vantiva) CGA
DOCSIS cable gateways. It reads the same JSON API as the gateway's web
interface: no cloud, no extra add-on.

It is built for long-term monitoring rather than for every raw field: a handful
of aggregated signal values worth graphing, and the gateway's DOCSIS event log
turned into persistent counters (disconnections, reboots, T3/T4 timeouts, ...).

Tested on an Orange Belgium **CGA437AORB** (firmware
`CGA437AORB-21.3-13.0-R024`) in router mode. Other CGA models share the same API
and are likely to work; reports are welcome.

## Features

| Entity | What it shows |
| --- | --- |
| Cable connection | On while the modem is registered (DOCSIS `OPERATIONAL`). |
| DOCSIS status | The raw cable modem status. |
| Downstream power (avg, min, max) | SC-QAM downstream power, in dBmV. The average carries the per-channel list as an attribute. |
| Downstream SNR (avg, min) | SC-QAM downstream SNR, in dB. |
| OFDM power / SNR | DOCSIS 3.1 downstream. |
| Upstream power (avg, max) | SC-QAM and OFDMA upstream power, in dBmV. |
| Downstream / upstream channels | Number of locked channels. |
| Corrected / uncorrectable codewords | Totals over all downstream channels. |
| Disconnections | One per re-registration (`CM State is operational`) found in the log, i.e. one per time the connection came back after being lost, including after a reboot. |
| Reboots | Detected from the uptime going back. |
| T3 timeouts, T4 timeouts, losses of sync, DHCP failures | Counted from the log. |
| Last log event | Time of the newest log line, with the recent lines as attributes. |
| DOCSIS log (event entity) | Fires once per new log line, typed `disconnection`, `reboot`, `t3_timeout`, `t4_timeout`, `sync_loss`, `dhcp_failure` or `other`: handy for automations and the logbook. |
| Wi-Fi log, system log, security log | Time of the newest entry of each gateway log (Wi-Fi events, system and eRouter events, firewall), with the last 20 entries as attributes. Read every 5 minutes. |
| Wi-Fi radio resets | The gateway's own count of *Radio … Interface Reset* events. A count that keeps rising means the Wi-Fi radio restarts over and over. |
| Last boot, CPU, memory, last reboot reason | Diagnostics. |
| Web interface in use | On while polling is paused, see below. |

Counters are stored by Home Assistant and survive restarts. What the log
already holds when the integration is added is treated as history and not
counted.

There are no per-channel entities on purpose: 20+ channels times a dozen
values is a lot of database for little use. The channel lists are available as
attributes, which are not recorded.

## The single web session

The gateway accepts one web session at a time. When somebody is logged in to
its web interface, logging in again either fails or logs that person out.

This integration keeps its session open between polls and **yields to people**:
when you log in to the web interface, it pauses (values stay as they were, the
*Web interface in use* sensor turns on) and tries again after 2 minutes, then
after longer and longer delays, so that refused logins never pile up. It logs
out when Home Assistant stops or the integration is unloaded, so the web
interface is free right away. If the integration itself left a session open
(after a crash), it ends that session on the next start.

If you prefer the integration to always win, enable **End other web sessions**
in its options.

## Installation

1. In HACS, open the menu → **Custom repositories**, add
   `https://github.com/Sr-0w/ha-technicolor-cga` with the category
   **Integration**, then download **Technicolor CGA cable gateway**.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Technicolor CGA cable
   gateway**, and enter the gateway's address (usually `192.168.0.1`), the web
   interface login (usually `user`) and its password.

## Development

The log and channel parsing lives in `parser.py`, which does not import Home
Assistant, and is tested against a real (anonymised) CGA437A answer:

```sh
python -m unittest discover -s tests -v
```

## License

MIT

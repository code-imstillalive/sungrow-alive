"""Diagnostics: what a tester attaches to an issue (Settings → Devices & services → Sungrow Alive →
⋮ → Download diagnostics).

It holds what the integration found and how the Logger answers: each device's kind, model, port and
address; the read plan; the connection's counters; and every value as it was last read, with its age.
The Logger's address, serial numbers and the config entry's unique id are redacted.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

TO_REDACT = {CONF_HOST, "serial", "unique_id"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    hub = entry.runtime_data
    now = time.time()
    stats = hub.scheduler.stats
    return {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "hub": {
            "gentle": hub.gentle,
            "read_only": hub.read_only,
            "moved_from_yaml": hub.legacy is not None,
            "devices": [async_redact_data(d.as_dict(), TO_REDACT) for d in hub.device_list],
            "reads": len(hub._reads),
            "blocks": len(hub.blocks),
            "readable": [list(s) for s in hub.readable],
            "unreadable": [list(s) for s in hub.unreadable],
        },
        "connection": {**asdict(stats), "started": None, "busy_fraction": round(stats.busy_fraction(), 3)},
        "values": {
            f"{dev}.{key}": {
                "value": "**REDACTED**" if "serial" in key else _plain(value),
                "age_s": round(now - hub.read_at[(dev, key)], 1) if (dev, key) in hub.read_at else None,
                "fresh": hub.is_fresh((dev, key)) if (dev, key) in hub.fields else None,
            }
            for (dev, key), value in sorted(hub.values.items())
        },
    }


def _plain(value: Any) -> Any:
    """A value as JSON can hold it: numbers, text, booleans and None as they are, anything else as text."""
    return value if value is None or isinstance(value, (bool, int, float, str)) else str(value)


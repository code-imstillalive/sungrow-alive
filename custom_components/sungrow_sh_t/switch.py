"""Switches: only the ones a Modbus YAML package had (see legacy.py); this integration's own
on/off settings are selects that name both states."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SungrowConfigEntry
from .legacy_entity import LegacySwitch


async def async_setup_entry(hass: HomeAssistant, entry: SungrowConfigEntry, add: AddEntitiesCallback) -> None:
    legacy = entry.runtime_data.legacy
    if legacy:
        add(LegacySwitch(entry.runtime_data, e) for e in legacy.entities if e.platform == "switch")

"""Sensors: every non-binary field, in the unit standard (quantities.py)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SungrowConfigEntry
from .entity import SungrowEntity
from .legacy_entity import LegacySensor
from .quantities import Q


async def async_setup_entry(hass: HomeAssistant, entry: SungrowConfigEntry, add: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    add(
        SungrowSensor(hub, entry.entry_id, dev, f)
        for (dev, _k), f in hub.fields.items()
        if f.platform == "sensor" and not f.control  # a setting with a control shows as that control
    )
    legacy = entry.runtime_data.legacy
    if legacy:
        add(LegacySensor(hub, e) for e in legacy.entities if e.platform == "sensor")


class SungrowSensor(SungrowEntity, SensorEntity):
    def __init__(self, hub, entry_id, dev, field) -> None:
        super().__init__(hub, entry_id, dev, field)
        q = Q[field.quantity]
        self._q = q
        if q.device_class:
            self._attr_device_class = SensorDeviceClass(q.device_class)
        if q.state_class and field.quantity not in ("enum", "text"):
            self._attr_state_class = SensorStateClass(q.state_class)
        self._attr_native_unit_of_measurement = q.unit
        if q.unit or field.quantity in ("power_factor", "count"):
            self._attr_suggested_display_precision = q.precision
        if field.quantity == "enum":
            names = list(dict.fromkeys((field.options or {}).values()))
            self._attr_options = names or None
            if not names:  # computed enum (e.g. export limit mode): plain text
                self._attr_device_class = None
        if field.attrs:
            self._attr_extra_state_attributes = dict(field.attrs)

    @property
    def native_value(self):
        v = self.raw_value
        if v is None or isinstance(v, (str, bool)):
            if self.device_class == SensorDeviceClass.ENUM and v not in (self.options or []):
                return None
            return v
        return v * self._q.factor

"""Binary sensors: the inverter's power-flow flags, plain and held for 60 s."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import SungrowConfigEntry
from .entity import SungrowEntity


async def async_setup_entry(hass: HomeAssistant, entry: SungrowConfigEntry, add: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    add(
        SungrowBinarySensor(hub, entry.entry_id, dev, f)
        for (dev, _k), f in hub.fields.items()
        if f.platform == "binary_sensor"
    )


class SungrowBinarySensor(SungrowEntity, BinarySensorEntity):
    """With `delay_on`, True must last that long before it shows (False shows at once)."""

    _pending: CALLBACK_TYPE | None = None
    _shown: bool | None = None

    def _changed(self) -> None:
        v = self.raw_value
        if not self.field.delay_on or not v:
            if self._pending:
                self._pending()
                self._pending = None
            self._shown = v
            self.async_write_ha_state()
            return
        if self._pending is None and not self._shown:
            self._pending = async_call_later(self.hass, self.field.delay_on, self._confirm)

    @callback
    def _confirm(self, _now) -> None:
        self._pending = None
        if self.raw_value:
            self._shown = True
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._pending:
            self._pending()

    @property
    def is_on(self) -> bool | None:
        return self._shown if self.field.delay_on else self.raw_value

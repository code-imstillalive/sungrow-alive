"""Number controls: every numeric setting, in the unit standard, with the device's own range.

A change is written ahead of every read, read back, and the control shows the
read-back, never the value asked for. A value the inverter does not keep is
reported as an error.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SungrowConfigEntry
from .entity import SungrowEntity
from .fields import encode_native
from .quantities import Q


async def async_setup_entry(hass: HomeAssistant, entry: SungrowConfigEntry, add: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    add(
        SungrowNumber(hub, entry.entry_id, dev, f)
        for (dev, _k), f in hub.fields.items()
        if f.control and f.control["kind"] == "number"
    )


class SungrowNumber(SungrowEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, hub, entry_id, dev, field) -> None:
        super().__init__(hub, entry_id, dev, field)
        self._q = Q[field.quantity]
        if self._q.device_class:
            try:
                self._attr_device_class = NumberDeviceClass(self._q.device_class)
            except ValueError:
                pass
        self._attr_native_unit_of_measurement = self._q.unit
        self._attr_native_step = field.control["step"] * self._q.factor

    def _bound(self, which: str) -> float:
        c = self.field.control
        if which in c:
            return c[which] * self._q.factor
        other = self.hub.values.get((self.dev, c.get(f"{which}_key", "")))
        if isinstance(other, (int, float)):
            return other * self._q.factor
        return 0.0 if which == "min" else 1e9

    @property
    def native_min_value(self) -> float:
        return self._bound("min")

    @property
    def native_max_value(self) -> float:
        return self._bound("max")

    @property
    def native_value(self) -> float | None:
        v = self.raw_value
        return None if v is None else v * self._q.factor

    async def async_set_native_value(self, value: float) -> None:
        if self.hub.read_only:
            raise HomeAssistantError(f"{self.name}: the Sungrow integration is set to read only (Configure)")
        if not self.native_min_value <= value <= self.native_max_value:
            raise HomeAssistantError(f"{self.name}: {value} is outside {self.native_min_value}-{self.native_max_value}")
        native = value / self._q.factor
        writes = self.field.control.get("writes")
        if writes:
            try:
                planned = writes(native, lambda k: self.hub.field_value(self.dev, k))
            except ValueError as err:  # the device has not reported what the write needs yet
                raise HomeAssistantError(f"{self.name}: {err}") from err
            done = await self.hub.write_many(self.dev, planned)
            bad = [(a, want, got) for a, want, got in done if want != got]
            if bad:
                raise HomeAssistantError(f"{self.name}: the inverter kept {bad}")
            return
        words = encode_native(self.field, native)
        back = await self.hub.write(self.dev, self.field.regs[0].address, words)
        if back != words:
            raise HomeAssistantError(f"{self.name}: the inverter kept {back}, not {words}")

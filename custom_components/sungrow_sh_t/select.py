"""Select controls: modes and commands (EMS mode, forced charge/discharge, curtailment, backup).

Written ahead of every read and read back; the control shows the read-back.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SungrowConfigEntry
from .entity import SungrowEntity
from .fields import encode_native


async def async_setup_entry(hass: HomeAssistant, entry: SungrowConfigEntry, add: AddEntitiesCallback) -> None:
    hub = entry.runtime_data
    add(
        SungrowSelect(hub, entry.entry_id, dev, f)
        for (dev, _k), f in hub.fields.items()
        if f.control and f.control["kind"] == "select"
    )


class SungrowSelect(SungrowEntity, SelectEntity):
    def __init__(self, hub, entry_id, dev, field) -> None:
        super().__init__(hub, entry_id, dev, field)
        if field.control.get("writes"):
            self._codes = {o: o for o in field.control["options"]}
        else:
            self._codes = {name: code for code, name in field.options.items()}
        self._attr_options = list(self._codes)

    @property
    def current_option(self) -> str | None:
        v = self.raw_value
        return v if v in self._codes else None

    async def async_select_option(self, option: str) -> None:
        if self.hub.read_only:
            raise HomeAssistantError(f"{self.name}: the Sungrow integration is set to read only (Configure)")
        writes = self.field.control.get("writes")
        if writes:
            try:
                planned = writes(option, lambda k: self.hub.field_value(self.dev, k))
            except ValueError as err:  # the device has not reported what the write needs yet
                raise HomeAssistantError(f"{self.name}: {err}") from err
            done = await self.hub.write_many(self.dev, planned)
            bad = [(a, want, got) for a, want, got in done if want != got]
            if bad:
                raise HomeAssistantError(f"{self.name}: the inverter kept {bad}")
            return
        words = encode_native(self.field, self._codes[option])
        back = await self.hub.write(self.dev, self.field.regs[0].address, words)
        if back != words:
            raise HomeAssistantError(f"{self.name}: the inverter kept {back}, not {words}")

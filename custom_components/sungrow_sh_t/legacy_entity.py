"""The entities that stand in for a Modbus YAML package's sensors and switches (see legacy.py).

Each one samples the hub at its own `scan_interval`, like the YAML entity did, and
writes a state only when the text changed; after a command or an
`homeassistant.update_entity` it shows the new value at once.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval

from . import legacy as L
from .hub import Hub, ReadOnlyError

_LOGGER = logging.getLogger(__name__)


class LegacyEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, hub: Hub, spec: L.LegacyEntity) -> None:
        self.hub, self.spec = hub, spec
        self._attr_unique_id = spec.unique_id
        self._attr_name = spec.name
        self._words = {(spec.port, spec.unit, spec.space, spec.address + i) for i in range(spec.count)}
        self._fresh = False
        self._first = None

    async def async_added_to_hass(self) -> None:
        interval = self.spec.scan_interval * self.hub.pace
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, timedelta(seconds=interval)))
        self.async_on_remove(self.hub.listen_words(self._commanded))
        self._sample(write=False)
        # until the first reading arrives, look every 2 s (not only every scan_interval), so a stand-in is
        # never "unavailable" for most of a minute after a start just because its turn came too early
        self._first = async_track_time_interval(self.hass, self._until_fresh, timedelta(seconds=2))
        self.async_on_remove(lambda: self._first and self._first())

    @callback
    def _until_fresh(self, _now=None) -> None:
        self._sample()
        if self._fresh and self._first:
            self._first()
            self._first = None

    @callback
    def _tick(self, _now=None) -> None:
        self._sample()

    @callback
    def _commanded(self, words: set) -> None:
        if words & self._words:
            self._sample()

    def _sample(self, write: bool = True) -> None:
        s = self.spec
        words, at = self.hub.read_words(s.port, s.unit, s.space, s.address, s.count)
        limit = max(3 * s.scan_interval * self.hub.pace, 30)
        fresh = words is not None and time.time() - at < limit
        changed = self._apply(words) if words is not None else False
        if changed or fresh != self._fresh:
            self._fresh = fresh
            if write:
                self.async_write_ha_state()

    def _apply(self, words: list[int]) -> bool:
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return self._fresh

    async def async_update(self) -> None:
        """`homeassistant.update_entity`: read the register now (scripts call it after a write)."""
        s = self.spec
        try:
            await self.hub.read_now(s.port, s.unit, s.space, s.address, s.count)
        except Exception as err:  # noqa: BLE001 - a script calling update_entity carries on, as with the YAML
            _LOGGER.warning("%s: refresh failed: %s", s.name, err)
            return
        self._sample(write=False)


class LegacySensor(LegacyEntity, SensorEntity):
    def __init__(self, hub: Hub, spec: L.LegacyEntity) -> None:
        super().__init__(hub, spec)
        self._attr_native_unit_of_measurement = spec.unit_of_measurement
        self._attr_device_class = spec.device_class
        self._attr_state_class = spec.state_class
        self._attr_native_value = None

    def _apply(self, words: list[int]) -> bool:
        v = L.sensor_state(self.spec, words)
        if v == self._attr_native_value:
            return False
        self._attr_native_value = v
        return True


class LegacySwitch(LegacyEntity, SwitchEntity):
    def __init__(self, hub: Hub, spec: L.LegacyEntity) -> None:
        super().__init__(hub, spec)
        self._attr_is_on = None

    def _apply(self, words: list[int]) -> bool:
        v = L.switch_state(self.spec, words[0])
        if v == self._attr_is_on:
            return False
        self._attr_is_on = v
        return True

    async def _command(self, value: int) -> None:
        s = self.spec
        try:
            await self.hub.write_port(s.port, s.unit, s.write_address, [value])
        except ReadOnlyError as err:
            raise HomeAssistantError(str(err)) from err
        if s.write_address != s.address or s.space != "holding":
            await self.async_update()  # the verify register is elsewhere: read it now
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._command(self.spec.command_on)

    async def async_turn_off(self, **kwargs) -> None:
        await self._command(self.spec.command_off)

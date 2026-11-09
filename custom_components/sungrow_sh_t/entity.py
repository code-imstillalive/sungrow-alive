"""The base every entity shares: its device, its field, and push updates from the hub."""

from __future__ import annotations

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import devices
from .fields import Field
from .hub import Hub

DOMAIN = "sungrow_sh_t"
#: fields the device page shows as the device reports them: model, serial number, firmware
REGISTRY_FIELDS = {"device_type": "model", "type": "model", "serial": "serial_number", "firmware": "sw_version"}


class SungrowEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: Hub, entry_id: str, dev: str, field: Field) -> None:
        self.hub, self.dev, self.field = hub, dev, field
        self._key = (dev, field.key)
        self._attr_unique_id = f"{entry_id}_{dev}_{field.key}"
        self._attr_name = field.name
        if field.category:
            self._attr_entity_category = EntityCategory(field.category)
        if not field.enabled:
            self._attr_entity_registry_enabled_default = False
        # the device itself (make, model, serial, parent) is registered at setup, parents first
        self._attr_device_info = DeviceInfo(identifiers={devices.identifier(entry_id, dev)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.listen(self._key, self._changed))
        self.async_on_remove(self.hub.listen_freshness(self._key, self.async_write_ha_state))
        if self._key in self.hub.values:  # already read before this entity existed
            self._changed()

    def _changed(self) -> None:
        self.async_write_ha_state()
        v = self.raw_value
        what = REGISTRY_FIELDS.get(self.field.key)
        if what and isinstance(v, str) and v.strip() and self.registry_entry and self.registry_entry.device_id:
            from homeassistant.helpers import device_registry as dr

            reg = dr.async_get(self.hass)
            device = reg.async_get(self.registry_entry.device_id)
            if device is not None and getattr(device, what) != v.strip():
                reg.async_update_device(device.id, **{what: v.strip()})

    @property
    def available(self) -> bool:
        return self.hub.is_fresh(self._key)

    @property
    def raw_value(self):
        return self.hub.values.get(self._key)

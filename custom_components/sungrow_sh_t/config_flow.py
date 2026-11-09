"""Set up: the Logger's address. Everything behind it is found by discovery and shown before it is kept.

Afterwards, Reconfigure searches the Logger again (devices found before keep their names and entity ids),
and Configure has the settings, which inverter each battery tower sits with, and devices to forget.
"""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from . import fields as F
from .devices import NO_INVERTER, forget, label as _label, set_towers, tower_choices
from .discovery import Result, discover, merge, open_ports
from .scheduler import OwnTransport

DOMAIN = "sungrow_sh_t"
CONF_DEVICES = "devices"
CONF_PORTS = "ports"
DEFAULT_PORT = 502  # Modbus TCP's own port
DEFAULT_PORTS = 8  # a Logger1000 can give each device its own port after the first


def _summary(result: Result, new: list[str] | None = None, missing: list[str] | None = None) -> str:
    """What was found, one line each; on a new search, which are new and which were not found this time."""
    names = {d.key: d.name for d in result.devices}

    def line(d: F.Device) -> str:
        where = f"with {names[d.inverter]}" if d.kind == "tower" and d.inverter in names else f"port {d.port}, address {d.unit}"
        tag = " (new)" if new and d.key in new else ""
        return f"- **{d.name}**{tag}: {d.model or 'model not reported'}{f', {d.serial}' if d.serial else ''} ({where})"

    lines = [line(d) for d in result.devices if not missing or d.key not in missing]
    if missing:
        lines.append("\nNot found this time, kept as they were (their entities stay): " + ", ".join(names[k] for k in missing) + ".")
    if result.expected is not None and not result.complete:
        found = sum(1 for d in result.devices if d.kind != "logger")
        lines.append(f"\nThe Logger counts {result.expected} devices; {found} of them answered as an inverter, battery tower or meter. Others (another make of meter, a third-party device) are not read.")
    return "\n".join(lines) or "Nothing answered."


class SungrowConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._host: str = ""
        self._first, self._count = DEFAULT_PORT, DEFAULT_PORTS
        self._task: asyncio.Task | None = None
        self._result: Result | None = None
        self._reconfiguring: ConfigEntry | None = None
        self._previous: list[F.Device] = []
        self._new: list[str] = []
        self._missing: list[str] = []

    async def _discover(self) -> Result:
        transport = OwnTransport(self._host, 1.5)
        try:
            ports = await open_ports(self._host, range(self._first, self._first + self._count))
            known = [(d.port, d.unit) for d in self._previous]  # a search again asks these first
            return await discover(transport.read, ports, known=known) if ports else Result()
        finally:
            transport.close()

    def _form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=self._host): str,
            vol.Required(CONF_PORT, default=self._first): vol.All(int, vol.Range(min=1, max=65535)),
            vol.Required(CONF_PORTS, default=self._count): vol.All(int, vol.Range(min=1, max=16)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors or {})

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self._form()
        self._host = user_input[CONF_HOST].strip()
        self._first, self._count = int(user_input[CONF_PORT]), int(user_input[CONF_PORTS])
        if not self._reconfiguring:
            await self.async_set_unique_id(self._host)
            self._abort_if_unique_id_configured()
        self._task = None
        return await self.async_step_discover()

    async def async_step_discover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._task is None:
            self._task = self.hass.async_create_task(self._discover())
        if not self._task.done():
            return self.async_show_progress(step_id="discover", progress_action="discover", progress_task=self._task)
        try:
            self._result = self._task.result()
        except Exception:  # noqa: BLE001 - a failed search is "nothing found", shown as such
            self._result = Result()
        if self._reconfiguring and self._result.devices:
            self._result.devices, self._new, self._missing = merge(self._previous, self._result.devices)
        return self.async_show_progress_done(next_step_id="confirm" if self._result.devices else "nothing")

    async def async_step_nothing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Nothing answered: back to the address, with the reason."""
        return self._form({"base": "nothing_found"})

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        result = self._result
        assert result is not None
        if user_input is not None:
            data = {CONF_HOST: self._host, CONF_PORT: self._first, CONF_DEVICES: [d.as_dict() for d in result.devices]}
            if self._reconfiguring:
                return self.async_update_reload_and_abort(self._reconfiguring, data={**self._reconfiguring.data, **data})
            logger = next((d for d in result.devices if d.kind == "logger"), None)
            return self.async_create_entry(title=f"Sungrow {logger.model if logger and logger.model else 'Logger'} ({self._host})", data=data)
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"devices": _summary(result, self._new, self._missing), "seconds": str(result.seconds)},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Search again (a device added or moved, or serial numbers a move from YAML did not record):
        devices found before keep their names and entity ids, and one not found is kept."""
        entry = self._get_reconfigure_entry()
        self._reconfiguring = entry
        self._host = entry.data[CONF_HOST]
        self._first = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self._previous = [F.Device.from_dict(d) for d in entry.data.get(CONF_DEVICES, [])]
        if user_input is None:
            return self._form()
        return await self.async_step_user(user_input)

    async def async_step_import(self, data: dict[str, Any]) -> ConfigFlowResult:
        """From `sungrow_sh_t:` in YAML (a former Modbus YAML package): the devices its hubs name."""
        await self.async_set_unique_id(data[CONF_HOST])
        self._abort_if_unique_id_configured()
        # a move from YAML starts with exactly the entities the house had: its own come later (Configure)
        return self.async_create_entry(title=f"Sungrow ({data[CONF_HOST]})", data=data, options={"own_entities": False})

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return SungrowOptionsFlow()


class SungrowOptionsFlow(OptionsFlow):
    """Settings (read only, gentle pace, own entities), which inverter each battery tower sits with, and
    devices to forget. Searching the Logger again is Reconfigure."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["settings", "towers", "forget"])

    def _save_devices(self, devices: list[dict[str, Any]]) -> ConfigFlowResult:
        """Write the device list and end; the entry reloads with it (its update listener)."""
        entry = self.config_entry
        self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_DEVICES: devices})
        return self.async_create_entry(data=dict(entry.options))

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required("read_only", default=o.get("read_only", False)): bool,
                vol.Required("gentle", default=o.get("gentle", False)): bool,
                vol.Required("own_entities", default=o.get("own_entities", True)): bool,
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_towers(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        raw = self.config_entry.data.get(CONF_DEVICES, [])
        devices = [F.Device.from_dict(d) for d in raw]
        towers = [d for d in devices if d.kind == "tower"]
        if not towers:
            return self.async_abort(reason="no_towers")
        if user_input is not None:
            return self._save_devices(set_towers(raw, user_input))
        guess = self._guess(devices)
        choices = tower_choices(devices)
        schema = vol.Schema(
            {
                vol.Required(t.key, default=t.inverter or guess.get(t.key, NO_INVERTER)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=choices, mode=selector.SelectSelectorMode.DROPDOWN)
                )
                for t in towers
            }
        )
        lines = "\n".join(f"- **{t.key}**: {_label(t)}{f', {t.serial}' if t.serial else ''}" for t in towers)
        return self.async_show_form(step_id="towers", data_schema=schema, description_placeholders={"towers": lines})

    def _guess(self, devices: list[F.Device]) -> dict[str, str]:
        """For a tower not yet placed: the inverter whose battery voltage its own matches now (the dashboard's rule)."""
        from homeassistant.helpers import entity_registry as er

        from . import stacks

        reg = er.async_get(self.hass)
        alias: dict[str, str] = {}
        for d in devices:
            for f in F.fields_for(d.kind):
                e = reg.async_get_entity_id(f.platform, DOMAIN, f"{self.config_entry.entry_id}_{d.key}_{f.key}")
                if e:
                    alias[f"{f.platform}.{slugify(f'{d.name} {f.name}')}"] = e
        found = stacks(self.hass, devices, alias)
        number = lambda key: int(key.rsplit("_", 1)[1])  # noqa: E731
        return {t.key: f"inverter_{found[number(t.key)][0]}" for t in devices if t.kind == "tower" and number(t.key) in found}

    async def async_step_forget(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        raw = self.config_entry.data.get(CONF_DEVICES, [])
        if user_input is not None:
            keys = list(user_input.get("devices", []))
            if not keys:
                return self.async_create_entry(data=dict(self.config_entry.options))
            return self._save_devices(forget(raw, keys))
        choices = [{"value": d.key, "label": _label(d)} for d in (F.Device.from_dict(x) for x in raw)]
        schema = vol.Schema(
            {vol.Optional("devices", default=[]): selector.SelectSelector(selector.SelectSelectorConfig(options=choices, multiple=True))}
        )
        return self.async_show_form(step_id="forget", data_schema=schema)

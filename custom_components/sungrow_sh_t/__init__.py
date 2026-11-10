"""Sungrow Alive: both inverters, the meter, the Logger and the battery towers,
through one Logger1000A, on one scheduler."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify

from . import devices as D
from . import fields as F
from . import layout
from . import legacy as L
from .hub import Hub, ReadOnlyError

_LOGGER = logging.getLogger(__name__)

CARDS_URL = "/sungrow_sh_t/sungrow-cards.js"

DOMAIN = "sungrow_sh_t"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SWITCH]
OPT_READ_ONLY = "read_only"
OPT_GENTLE = "gentle"
OPT_OWN = "own_entities"  # False: only the YAML stand-ins (the first step of a move from YAML)

# `sungrow_sh_t:` in YAML is a former `modbus:` hub list (see legacy.py); merged across packages like modbus's
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.All(cv.ensure_list, [dict])}, extra=vol.ALLOW_EXTRA)

WRITE_SCHEMA = vol.Schema(
    {
        vol.Required("hub"): cv.string,
        vol.Required("address"): vol.Coerce(int),
        vol.Required("value"): vol.Any(vol.Coerce(int), [vol.Coerce(int)]),
        vol.Optional("slave"): vol.Coerce(int),
        vol.Optional("device_address"): vol.Coerce(int),
        vol.Optional("unit"): vol.Coerce(int),
    }
)

type SungrowConfigEntry = ConfigEntry[Hub]

CONF_DEVICES = "devices"

# Version 1 entries (before discovery) had no device list: the layout was fixed
# in code, the one of the Logger it was first written against, counted from the
# entry's first port. Migration writes exactly that out, so nothing is renamed.
_V1_LAYOUT = (
    ("inverter", 1, 0, 1), ("inverter", 2, 1, 2), ("meter", 0, 2, 5), ("logger", 0, 3, 247),
    ("tower", 1, 4, 6), ("tower", 3, 5, 3), ("tower", 2, 6, 7), ("tower", 4, 7, 4),
)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version == 1:
        base = entry.data.get(CONF_PORT, 502)
        devices = [F.device(kind, n, base + offset, unit).as_dict() for kind, n, offset, unit in _V1_LAYOUT]
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_DEVICES: devices}, version=2, unique_id=entry.data[CONF_HOST])
        _LOGGER.info("Sungrow entry %s: device list written from the version 1 layout", entry.entry_id)
    return entry.version == 2


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The YAML stand-in (if any), its import into a config entry, and the write service."""
    conf = config.get(DOMAIN)
    legacy = L.parse(conf) if conf else None  # a mistake in the YAML stops here, before anything is taken over
    hass.data[f"{DOMAIN}_legacy"] = legacy
    if legacy and legacy.entities and not hass.config_entries.async_entries(DOMAIN):
        host = next(iter(legacy.hubs.values()))[0]
        port = min(p for _h, p in legacy.hubs.values())
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT},
                data={CONF_HOST: host, CONF_PORT: port, CONF_DEVICES: [d.as_dict() for d in L.devices_from_yaml(conf)]},
            )
        )

    async def write_register(call: ServiceCall) -> None:
        legacy = hass.data.get(f"{DOMAIN}_legacy")
        name = call.data["hub"]
        if not legacy or name not in legacy.hubs:
            raise ServiceValidationError(f"no Sungrow hub named {name!r} under sungrow_sh_t: in YAML")
        hubs = [e.runtime_data for e in hass.config_entries.async_loaded_entries(DOMAIN) if e.runtime_data.legacy]
        if not hubs:
            raise HomeAssistantError("the Sungrow integration is not running")
        unit = next((call.data[k] for k in ("slave", "device_address", "unit") if k in call.data), None)
        if unit is None:
            unit = next((e.unit for e in legacy.entities if e.hub == name), 1)
        value = call.data["value"]
        values = value if isinstance(value, list) else [value]
        try:
            await hubs[0].write_port(legacy.hub_port(name), unit, call.data["address"], values)
        except ReadOnlyError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(DOMAIN, "write_register", write_register, schema=WRITE_SCHEMA)
    websocket_api.async_register_command(hass, ws_app)
    return True


def app_config(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """The dashboard for this entry's devices: laid out by name, trimmed to the entities that exist,
    with every entity the user renamed (or that Home Assistant suffixed) mapped to its real id."""
    devices = [F.Device.from_dict(d) for d in entry.data.get(CONF_DEVICES, [])]
    reg = er.async_get(hass)
    by_uid = {e.unique_id: e for e in er.async_entries_for_config_entry(reg, entry.entry_id) if not e.disabled_by}
    exists: set[str] = set()
    alias: dict[str, str] = {}
    for d in devices:
        for f in F.fields_for(d.kind):
            e = by_uid.get(f"{entry.entry_id}_{d.key}_{f.key}")
            if e is None:
                continue
            named = f"{e.domain}.{slugify(f'{d.name} {f.name}')}"
            exists.add(named)
            if e.entity_id != named:
                alias[named] = e.entity_id
    numbers = lambda kind: [int(d.key.rsplit("_", 1)[1]) for d in devices if d.kind == kind]
    app = layout.build(numbers("inverter"), numbers("tower"), stacks(hass, devices, alias))["views"][0]["cards"][0]
    pruned = layout.prune(app, exists)
    return {"config": pruned if isinstance(pruned, dict) else {"pages": []}, "alias": alias}


def stacks(hass: HomeAssistant, devices: list[F.Device], alias: dict[str, str]) -> dict[int, tuple[int, str]]:
    """Each tower's battery stack: tower number -> (its inverter's number, that inverter's model or name).
    Discovery records it; a tower from before (or from the YAML move) is matched to the inverter whose
    battery voltage its own is within 3 % of, read live, and left out when none is."""
    inverters = {d.key: d for d in devices if d.kind == "inverter"}
    num = lambda key: int(key.rsplit("_", 1)[1])

    def volts(entity_id: str) -> float | None:
        s = hass.states.get(alias.get(entity_id, entity_id))
        try:
            return float(s.state) if s is not None else None
        except ValueError:
            return None

    def model(inv: F.Device) -> str:
        """As discovery recorded it, else as the inverter reports it now, else its name."""
        if inv.model:
            return inv.model
        s = hass.states.get(alias.get(f"sensor.{slugify(inv.name)}_model", f"sensor.{slugify(inv.name)}_model"))
        return s.state if s is not None and s.state not in ("unknown", "unavailable") else inv.name

    out: dict[int, tuple[int, str]] = {}
    for t in (d for d in devices if d.kind == "tower"):
        inv = inverters.get(t.inverter or "")
        if inv is None:
            mine = volts(f"sensor.{slugify(t.name)}_voltage")
            best = 0.03
            for cand in inverters.values():
                theirs = volts(f"sensor.{slugify(cand.name)}_battery_voltage")
                if mine and theirs and abs(mine - theirs) / theirs < best:
                    inv, best = cand, abs(mine - theirs) / theirs
        if inv is not None:
            out[num(t.key)] = (num(inv.key), model(inv))
    return out


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/app", vol.Optional("entry_id"): str})
@callback
def ws_app(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The Sungrow app card asks for its pages: the first loaded entry with its own entities on (or the one named)."""
    entries = [e for e in hass.config_entries.async_loaded_entries(DOMAIN) if not msg.get("entry_id") or e.entry_id == msg["entry_id"]]
    entries.sort(key=lambda e: not e.options.get(OPT_OWN, True))
    if not entries:
        connection.send_error(msg["id"], "not_found", "no Sungrow integration is running")
        return
    connection.send_result(msg["id"], app_config(hass, entries[0]))


async def _register_cards(hass: HomeAssistant) -> None:
    """Serve the power-flow and day cards from this integration (once per run)."""
    from pathlib import Path

    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    if hass.data.get(f"{DOMAIN}_cards"):
        return
    hass.data[f"{DOMAIN}_cards"] = True
    www = Path(__file__).parent / "www"
    version = int(await hass.async_add_executor_job(lambda: max(f.stat().st_mtime for f in www.glob("*.js"))))
    await hass.http.async_register_static_paths([StaticPathConfig("/sungrow_sh_t", str(www), False)])
    url = f"{CARDS_URL}?v={version}"
    try:
        registered = await _async_card_resource(hass, url)
    except Exception:  # noqa: BLE001 - the extra module below still loads the cards
        _LOGGER.debug("Sungrow: dashboard resource not registered", exc_info=True)
        registered = False
    if not registered:
        add_extra_js_url(hass, url)


async def _async_card_resource(hass: HomeAssistant, url: str) -> bool:
    """The cards as a dashboard resource, as HACS cards load; True when done.

    Loaded as Home Assistant's extra module, the cards lost a race on a plain
    refresh: a dashboard built a moment before them showed "Custom element
    doesn't exist: sungrow-app" and, on a panel view, never built them again
    (10 Nov 2026). As a dashboard resource they did not. An existing resource
    for this file (one added by hand) is brought to the current version rather
    than added twice. False on a dashboard in YAML mode, which has no resource
    store: the caller then uses the extra module."""
    data = hass.data.get("lovelace")
    resources = getattr(data, "resources", None)
    if resources is None and isinstance(data, dict):
        resources = data.get("resources")
    if resources is None or not hasattr(resources, "async_create_item"):
        return False
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True
    for item in resources.async_items():
        if str(item.get("url", "")).split("?")[0] == CARDS_URL:
            if item.get("url") != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return True
    await resources.async_create_item({"res_type": "module", "url": url})
    return True


def _take_over_ids(hass: HomeAssistant, entry: ConfigEntry, legacy: L.LegacyConfig) -> None:
    """Give each stand-in entity the entity id its `modbus` YAML entity had, with what the user set on it.

    Only an id whose `modbus` entity is gone (no state, or a restored placeholder) is taken.
    """
    reg = er.async_get(hass)
    taken = 0
    for e in legacy.entities:
        if reg.async_get_entity_id(e.platform, DOMAIN, e.unique_id):
            continue  # ours already
        old_id = reg.async_get_entity_id(e.platform, "modbus", e.yaml_unique_id)
        if not old_id:
            continue
        state = hass.states.get(old_id)
        if state is not None and not state.attributes.get("restored"):
            _LOGGER.warning("%s is still provided by Modbus; left to it", old_id)
            continue
        old = reg.async_get(old_id)
        reg.async_remove(old_id)
        new = reg.async_get_or_create(
            e.platform, DOMAIN, e.unique_id, suggested_object_id=old_id.split(".", 1)[1], config_entry=entry
        )
        if new.entity_id != old_id:
            _LOGGER.warning("%s could not be taken over (now %s)", old_id, new.entity_id)
            continue
        reg.async_update_entity(
            new.entity_id,
            name=old.name,
            icon=old.icon,
            area_id=old.area_id,
            hidden_by=old.hidden_by,
            disabled_by=old.disabled_by,
            aliases=old.aliases,
            labels=old.labels,
        )
        for domain, opts in (old.options or {}).items():
            reg.async_update_entity_options(new.entity_id, domain, dict(opts))
        taken += 1
    if taken:
        _LOGGER.info("took over %d entity ids from the Modbus YAML", taken)


async def async_setup_entry(hass: HomeAssistant, entry: SungrowConfigEntry) -> bool:
    await _register_cards(hass)
    host = entry.data[CONF_HOST]
    legacy: L.LegacyConfig | None = hass.data.get(f"{DOMAIN}_legacy")
    if legacy and any(hh != host for hh, _p in legacy.hubs.values()):
        legacy = None  # the YAML names another Logger: this entry is not its stand-in (a test beside it, say)
    if legacy:
        _take_over_ids(hass, entry, legacy)
    try:  # Home Assistant's shared Modbus connections, 2026.11 and later
        from .ha_transport import HaTransport

        transport = HaTransport(hass, entry, host, timeout=3.0)
    except ImportError:  # older Home Assistant: this integration's own client
        transport = None
    # what this Logger has answered, learned on this install (never shipped)
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.readable")
    learned = await store.async_load() or {}
    hub = await hass.async_add_executor_job(
        lambda: Hub(
            host,
            [F.Device.from_dict(d) for d in entry.data[CONF_DEVICES]],
            transport,
            extra_reads=legacy.reads() if legacy else (),
            gentle=entry.options.get(OPT_GENTLE, False),
            read_only=entry.options.get(OPT_READ_ONLY, False),
            own_entities=entry.options.get(OPT_OWN, True),
            readable=[tuple(x) for x in learned.get("readable", [])],
            unreadable=[tuple(x) for x in learned.get("unreadable", [])],
        )
    )
    hub.legacy = legacy
    _register_devices(hass, entry, hub.device_list)
    hub.start(lambda coro: entry.async_create_background_task(hass, coro, "sungrow_sh_t scheduler"))
    entry.runtime_data = hub

    async def survey() -> None:
        """Learn which gaps this Logger reads across, quietly, then keep using the merged plan."""
        await asyncio.sleep(120)  # let the first readings settle
        while hub.survey_todo():
            done = await hub.survey()
            await store.async_save({"readable": hub.readable, "unreadable": hub.unreadable})
            if done:
                _LOGGER.info("Sungrow: learned this Logger's readable gaps (%d readable, %d refused)", len(hub.readable), len(hub.unreadable))
                break
            await asyncio.sleep(600)  # the link dropped: try again later

    entry.async_create_background_task(hass, survey(), "sungrow_sh_t survey")  # reads only, read-only mode included
    entry.async_on_unload(entry.add_update_listener(_options_changed))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _register_devices(hass: HomeAssistant, entry: ConfigEntry, devices: list[F.Device]) -> None:
    """Every device on its page, parents first, so each tower sits under its inverter and the rest under the Logger."""
    reg = dr.async_get(hass)
    by_id = "via_device_id" in inspect.signature(reg.async_get_or_create).parameters  # Home Assistant 2026.11 and later
    made: dict[tuple[str, str], str] = {}  # identifier -> device id, parents first
    for d in D.in_order(devices):
        info = D.info(entry.entry_id, d, devices)
        if by_id:
            info["via_device_id"] = made.get(info.pop("via_device", None))
        made[D.identifier(entry.entry_id, d.key)] = reg.async_get_or_create(config_entry_id=entry.entry_id, **info).id
    # a device forgotten in Configure goes, with its entities (a search keeps one it does not find)
    keep = {D.identifier(entry.entry_id, d.key) for d in devices}
    for device in dr.async_entries_for_config_entry(reg, entry.entry_id):
        if not device.identifiers & keep and any(i[0] == DOMAIN for i in device.identifiers):
            reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def async_remove_config_entry_device(hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry) -> bool:
    """A device can be deleted from its page once the entry no longer has it (it left in a new search)."""
    keys = {d["key"] for d in entry.data.get(CONF_DEVICES, [])}
    return not any(ident[0] == DOMAIN and ident[1].removeprefix(f"{entry.entry_id}_") in keys for ident in device.identifiers)


async def _options_changed(hass: HomeAssistant, entry: SungrowConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SungrowConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.stop()
    return ok

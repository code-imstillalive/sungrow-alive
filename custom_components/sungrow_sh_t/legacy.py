"""Standing in for a Modbus YAML package: same entities, same ids, same values, one scheduler.

A house that already runs the Sungrow registers as YAML (`modbus:` hubs with
sensors and switches, and templates, scripts and dashboards built on them)
renames that one key to `sungrow_sh_t:` and its `modbus.write_register` calls
to `sungrow_sh_t.write_register`. Everything else stays as it is.

This integration then:
- reads every register those entities read, at each entity's own
  `scan_interval`, merged into its own plan (one request in flight on the bus);
- gives every YAML sensor and switch back as an entity with the same unique id,
  the same entity id (it takes over the id the `modbus` entity leaves behind),
  and the same state text, decoded exactly as Home Assistant's Modbus sensor
  decodes it (decode.py), so history and every template carry on unchanged;
- writes `sungrow_sh_t.write_register` calls through its scheduler, by hub name.

Putting the key back to `modbus:` returns the house to the YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import decode
from . import fields as F

#: (domain, unique id) of every entity this layer creates is ("sensor"|"switch", PREFIX + YAML unique id)
PREFIX = "yaml_"


@dataclass
class LegacyEntity:
    platform: str  # "sensor" or "switch"
    hub: str
    yaml_unique_id: str
    name: str
    port: int
    unit: int  # the Modbus device address
    space: str  # "input" or "holding" (what is read)
    address: int
    count: int
    scan_interval: int
    spec: decode.Spec | None = None  # sensors
    unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    # switches
    command_on: int | None = None
    command_off: int | None = None
    state_on: int | None = None
    state_off: int | None = None
    write_address: int | None = None

    @property
    def unique_id(self) -> str:
        return PREFIX + self.yaml_unique_id


@dataclass
class LegacyConfig:
    hubs: dict[str, tuple[str, int]] = field(default_factory=dict)  # name -> (host, port)
    entities: list[LegacyEntity] = field(default_factory=list)

    def reads(self) -> list[tuple[int, int, str, int, int, int]]:
        return [(e.port, e.unit, e.space, e.address, e.count, e.scan_interval) for e in self.entities]

    def hub_port(self, name: str) -> int:
        return self.hubs[name][1]


def _unit(e: dict[str, Any]) -> int:
    for k in ("device_address", "slave", "unit"):
        if e.get(k) is not None:
            return int(e[k])
    return 0


def parse(conf: list[dict[str, Any]]) -> LegacyConfig:
    """The `sungrow_sh_t:` YAML (the former `modbus:` hubs). Raises ValueError on what it cannot stand in for."""
    out = LegacyConfig()
    for hub in conf or []:
        name = hub["name"]
        if hub.get("type", "tcp") != "tcp":
            raise ValueError(f"{name}: only tcp hubs")
        out.hubs[name] = (str(hub["host"]), int(hub["port"]))
        port = int(hub["port"])
        for e in hub.get("sensors") or []:
            spec = decode.Spec.from_entry(e)
            out.entities.append(LegacyEntity(
                "sensor", name, e["unique_id"], e["name"], port, _unit(e),
                e.get("input_type", "holding"), int(e["address"]), spec.count,
                int(e.get("scan_interval", 15)), spec=spec,
                unit_of_measurement=e.get("unit_of_measurement"),
                device_class=e.get("device_class"), state_class=e.get("state_class"),
            ))
        for e in hub.get("switches") or []:
            if e.get("write_type", "holding") != "holding":
                raise ValueError(f"{e.get('name')}: only holding-register switches")
            verify = e.get("verify") or {}
            on, off = int(e.get("command_on", 1)), int(e.get("command_off", 0))
            out.entities.append(LegacyEntity(
                "switch", name, e["unique_id"], e["name"], port, _unit(e),
                verify.get("input_type", "holding"), int(verify.get("address", e["address"])), 1,
                int(e.get("scan_interval", 15)),
                command_on=on, command_off=off,
                state_on=int(verify.get("state_on", on)), state_off=int(verify.get("state_off", off)),
                write_address=int(e["address"]),
            ))
        for kind in ("binary_sensors", "climates", "covers", "fans", "lights"):
            if hub.get(kind):
                raise ValueError(f"{name}: {kind} are not supported")
    return out


def sensor_state(e: LegacyEntity, words: list[int]) -> str | None:
    """The state text Home Assistant's Modbus sensor would show for these words."""
    return decode.decode(e.spec, words)


def switch_state(e: LegacyEntity, word: int) -> bool | None:
    if word == e.state_on:
        return True
    if word == e.state_off:
        return False
    return None


def _kind(addresses: set[tuple[str, int]], unit: int) -> str | None:
    """What a YAML hub reads tells what the device is (protocol register ranges)."""
    if unit == 247:
        return "logger"
    if any(sp == "input" and 10700 <= a < 10800 for sp, a in addresses):
        return "tower"
    if any(sp == "holding" and 4096 <= a < 4700 for sp, a in addresses):
        return "meter"
    if any(4989 <= a < 5800 or 12999 <= a < 13200 or 31200 <= a < 33200 for _sp, a in addresses):
        return "inverter"
    return None


def devices_from_yaml(conf: list[dict[str, Any]]) -> list[F.Device]:
    """The devices a former Modbus YAML package reads, classified by their registers and numbered as the
    package itself names them ("... inv2", "battery tower 3"), in port order otherwise. No Logger traffic."""
    import re

    groups: dict[tuple[int, int], dict[str, Any]] = {}
    for hub in conf or []:
        port = int(hub["port"])
        for e in [*(hub.get("sensors") or []), *(hub.get("switches") or [])]:
            g = groups.setdefault((port, _unit(e)), {"addresses": set(), "names": []})
            g["addresses"].add((e.get("input_type", "holding"), int(e["address"])))
            g["names"].append(f"{hub['name']} {e.get('name', '')}".lower())
    found: list[tuple[str, int | None, int, int]] = []
    for (port, unit), g in sorted(groups.items()):
        kind = _kind(g["addresses"], unit)
        if not kind:
            continue
        pattern = r"tower[ _]?(\d+)" if kind == "tower" else r"inv(?:erter)?[ _]?(\d+)\b"
        numbers = {int(m) for n in g["names"] for m in re.findall(pattern, n)}
        found.append((kind, numbers.pop() if len(numbers) == 1 else None, port, unit))
    devices = []
    for kind in ("inverter", "tower"):
        mine = [f for f in found if f[0] == kind]
        taken = {n for _k, n, _p, _u in mine if n}
        free = (n for n in range(1, 100) if n not in taken)
        for _k, n, port, unit in mine:
            devices.append(F.device(kind, n or next(free), port, unit))
    for kind in F.SINGLE:
        one = next((f for f in found if f[0] == kind), None)
        if one:
            devices.append(F.device(kind, 0, one[2], one[3]))
    return devices

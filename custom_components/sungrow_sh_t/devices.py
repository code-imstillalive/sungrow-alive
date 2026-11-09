"""Each device as Home Assistant's device page shows it: make, model, serial number, and where it sits.

The Logger is the parent of every inverter and the meter; a battery tower sits under the inverter whose
battery stack it is part of (under the Logger while that is not known). Pure: no Home Assistant import,
so the shape is tested without it.
"""

from __future__ import annotations

from typing import Any

from . import fields as F

DOMAIN = "sungrow_sh_t"
NO_INVERTER = "none"  # a tower whose inverter is not known


def identifier(entry_id: str, key: str) -> tuple[str, str]:
    return (DOMAIN, f"{entry_id}_{key}")


def parent(device: F.Device, devices: list[F.Device]) -> str | None:
    """The key of the device this one is connected through, or None for the Logger (or a site without one)."""
    keys = {d.key for d in devices}
    if device.kind == "logger":
        return None
    if device.kind == "tower" and device.inverter in keys:
        return device.inverter
    return "logger" if "logger" in keys else None


def info(entry_id: str, device: F.Device, devices: list[F.Device]) -> dict[str, Any]:
    """The device registry's fields for one device (a DeviceInfo)."""
    out: dict[str, Any] = {
        "identifiers": {identifier(entry_id, device.key)},
        "name": device.name,
        "manufacturer": "CHINT" if device.kind == "meter" else "Sungrow",
    }
    model = device.model or ("DTSU666-20" if device.kind == "meter" else None)  # the meter has no model register
    if model:
        out["model"] = model
    if device.serial:
        out["serial_number"] = device.serial
    up = parent(device, devices)
    if up:
        out["via_device"] = identifier(entry_id, up)
    return out


def in_order(devices: list[F.Device]) -> list[F.Device]:
    """Parents before the devices under them: the registry links a device only to one it already has."""
    depth = {"logger": 0, "inverter": 1, "meter": 1, "tower": 2}
    return sorted(devices, key=lambda d: depth.get(d.kind, 3))


def label(d: F.Device) -> str:
    return f"{d.name} ({d.model})" if d.model else d.name


def tower_choices(devices: list[F.Device]) -> list[dict[str, str]]:
    """The inverters a tower can sit with, by name and model, and "not known"."""
    return [{"value": d.key, "label": label(d)} for d in devices if d.kind == "inverter"] + [{"value": NO_INVERTER, "label": "Not known"}]


def set_towers(devices: list[dict[str, Any]], chosen: dict[str, str]) -> list[dict[str, Any]]:
    """The entry's device list with each tower's inverter as chosen (a tower not in `chosen` is unchanged)."""
    out = []
    for d in devices:
        d = dict(d)
        if d.get("kind") == "tower" and d["key"] in chosen:
            d.pop("inverter", None)
            if chosen[d["key"]] != NO_INVERTER:
                d["inverter"] = chosen[d["key"]]
        out.append(d)
    return out


def forget(devices: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    """The entry's device list without `keys`; a tower that sat with a forgotten inverter is then "not known"."""
    out = [dict(d) for d in devices if d["key"] not in keys]
    for d in out:
        if d.get("inverter") in keys:
            d.pop("inverter")
    return out

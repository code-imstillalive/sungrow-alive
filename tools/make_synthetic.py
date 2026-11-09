"""Make the simulator's site data from nothing but the integration's own field list: no install's values.

Writes data/synthetic/register_map.json (a Modbus YAML package's shape, one hub per device) and
data/synthetic/seed.json (every register each device's fields read, plus the registers between them,
so the survey has gaps to learn). The site has the same shape as the one the tests were written
against (two SH-T inverters, four towers, a CHINT meter, a Logger, one port each from 502), but its
serial numbers, readings and address are invented. The host is from 192.0.2.0/24, the range kept for
documentation.

    python tools/make_synthetic.py
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "sungrow_sh_t"
pkg = types.ModuleType("sungrow_sh_t")
pkg.__path__ = [str(PKG)]
sys.modules.setdefault("sungrow_sh_t", pkg)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"sungrow_sh_t.{name}", PKG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"sungrow_sh_t.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load("fields")

HOST = "192.0.2.10"
#: (kind, number, port, unit, model code, serial, battery volts): an invented site of the tests' shape.
#: Serials differ before their last character, which the simulator raises to make a copy's own.
SITE = (
    ("inverter", 1, 502, 1, 0x0E28, "XSYN1INV00", 590.0),
    ("inverter", 2, 503, 2, 0x0E25, "XSYN2INV00", 410.0),
    ("meter", 0, 504, 5, None, None, None),
    ("logger", 0, 505, 247, 0x0710, None, None),
    ("tower", 1, 506, 6, 0x20F7, "XSYN1TWR00", 591.0),
    ("tower", 3, 507, 3, 0x20EC, "XSYN3TWR00", 409.0),
    ("tower", 2, 508, 7, 0x20F7, "XSYN2TWR00", 589.5),
    ("tower", 4, 509, 4, 0x20EC, "XSYN4TWR00", 410.5),
)


def _text(s: str, words: int) -> list[int]:
    b = s.encode("ascii").ljust(2 * words, b"\0")[: 2 * words]
    return [(b[i] << 8) | b[i + 1] for i in range(0, len(b), 2)]


def _plain(reg, field) -> list[int]:
    """A value that decodes cleanly: the first option of an enum, small numbers otherwise."""
    if reg.type.startswith("str"):
        return _text("XSYN", reg.count)
    if field.options:
        code = next(iter(field.options))
        return [code & 0xFFFF] + [0] * (reg.count - 1) if reg.count == 1 else [0] * (reg.count - 1) + [code & 0xFFFF]
    if reg.count == 1:
        return [100]
    return [0] * (reg.count - 1) + [100]


def _device(kind, number, port, unit, model, serial, volts):
    regs: dict[str, dict[int, int]] = {"input": {}, "holding": {}}
    fields = F.fields_for(kind)
    for f in fields:
        for r in f.regs:
            for i, v in enumerate(_plain(r, f)):
                regs[r.space][r.address + i] = v
    # identity and the readings discovery uses, as a real device would answer them
    if kind == "inverter":
        regs["input"][4999] = model
        for i, v in enumerate(_text(serial, 10)):
            regs["input"][4989 + i] = v
        regs["input"][13019] = int(volts * 10)
    elif kind == "tower":
        regs["input"][10709] = model
        for i, v in enumerate(_text(serial, 10)):
            regs["input"][10710 + i] = v
        regs["input"][10740] = int(volts * 10)
    elif kind == "meter":
        for j in range(3):  # phase voltages, 0.1 V, high word first
            regs["holding"][4358 + 2 * j], regs["holding"][4359 + 2 * j] = 0, 2400 + j
    elif kind == "logger":
        regs["input"][7999] = model
        regs["input"][8004] = sum(1 for s in SITE if s[0] != "logger")
    # the registers between a device's fields read as zero, so the survey has gaps to learn
    for space, values in regs.items():
        if values:
            lo, hi = min(values), max(values)
            for a in range(lo, hi + 1):
                if hi - lo < 4000:
                    values.setdefault(a, 0)
    return regs, fields


def main() -> None:
    out = ROOT / "data" / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    hubs, seed = [], {}
    for kind, number, port, unit, model, serial, volts in SITE:
        regs, fields = _device(kind, number, port, unit, model, serial, volts)
        for space, values in regs.items():
            if values:
                seed[f"{port}/{unit}/{space}"] = {str(a): {"value": v, "from": "synthetic"} for a, v in sorted(values.items())}
        label = {"inverter": f"inv{number}", "tower": f"battery tower {number}", "meter": "meter", "logger": "logger"}[kind]
        entities = []
        for f in fields:
            r = f.regs[0]
            entities.append({
                "name": f"{label} {f.name}",
                "unique_id": f"synthetic_{kind}{number}_{f.key}",
                "address": r.address,
                "input_type": r.space,
                "data_type": "string" if r.type.startswith("str") else "uint16" if r.count == 1 else "uint32",
                **({"count": r.count} if r.type.startswith("str") else {}),
                "slave": unit,
                "unit": unit,
                "scan_interval": 30,
                "platform": "sensor",
            })
        hubs.append({"file": f"synthetic_{label.replace(' ', '_')}.yaml", "hub": f"Synthetic_{label.replace(' ', '_')}",
                     "type": "tcp", "host": HOST, "port": port, "timing": {}, "entities": entities})
    (out / "register_map.json").write_text(json.dumps({"source": "tools/make_synthetic.py", "hubs": hubs}, indent=1) + "\n")
    (out / "seed.json").write_text(json.dumps({"taken": "synthetic", "registers": seed, "report": {}}) + "\n")
    print(f"{len(hubs)} devices, {sum(len(v) for v in seed.values())} registers -> {out}")


if __name__ == "__main__":
    main()

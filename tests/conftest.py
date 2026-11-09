"""Tests for the parts of the integration that need no Home Assistant: discovery, the YAML move's
device list, the planner, the scheduler, the dashboard layout, the fields.

The integration's package is made importable without running its __init__ (which imports Home
Assistant), and the simulator (sim/simulator.py) is served in-process on free ports, in any of the
layouts in sim/layouts.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pathlib
import socket
import sys
import types
from contextlib import asynccontextmanager

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "sungrow_sh_t"

_pkg = types.ModuleType("sungrow_sh_t")
_pkg.__path__ = [str(PKG)]
sys.modules.setdefault("sungrow_sh_t", _pkg)


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SIM = load(ROOT / "sim" / "simulator.py", "sungrow_sim")

#: the site the simulator plays: invented (tools/make_synthetic.py) when SUNGROW_SYNTHETIC is set or
#: no recorded site is present, else the recorded one
SYNTHETIC = bool(os.environ.get("SUNGROW_SYNTHETIC")) or not (ROOT / "data/seed_ha.json").exists()
REGMAP = ROOT / ("data/synthetic/register_map.json" if SYNTHETIC else "data/register_map.json")
SEED = ROOT / ("data/synthetic/seed.json" if SYNTHETIC else "data/seed_ha.json")

#: this house's layout, as the version 1 integration fixed it: (kind, number, port offset, unit)
HOUSE = (
    ("inverter", 1, 0, 1), ("inverter", 2, 1, 2), ("meter", 0, 2, 5), ("logger", 0, 3, 247),
    ("tower", 1, 4, 6), ("tower", 3, 5, 3), ("tower", 2, 6, 7), ("tower", 4, 7, 4),
)


def free_base() -> int:
    """A first port with the next 7 free too."""
    for _ in range(50):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            base = s.getsockname()[1]
        if base + 8 < 65535 and all(_free(base + i) for i in range(8)):
            return base
    raise RuntimeError("no 8 free ports")


def _free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@asynccontextmanager
async def site(layout: str | None = None, control: pathlib.Path | None = None):
    """The simulator as a Logger on 127.0.0.1: yields its first port (devices at their real offsets from it)."""
    base = free_base()
    regmap = json.loads(REGMAP.read_text())
    seed = json.loads(SEED.read_text())
    dumps_path = ROOT / "data/survey_dumps.json"
    dumps = json.loads(dumps_path.read_text()) if dumps_path.exists() and not SYNTHETIC else []
    store = SIM.Store(regmap, seed, dumps, base)
    if layout:
        store.relayout(json.loads((ROOT / "sim" / "layouts" / f"{layout}.json").read_text()), base)
    bus = SIM.Bus(0.0, 0.0)
    args = types.SimpleNamespace(host="127.0.0.1", control=str(control) if control else None)
    servers = [await SIM.serve_port(p, store, bus, args) for p in sorted(store.units_by_port)]
    try:
        yield base
    finally:
        for s in servers:
            s.close()
            await s.wait_closed()


def run(coro):
    return asyncio.run(coro)

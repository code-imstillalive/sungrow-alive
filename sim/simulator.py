"""A Modbus TCP simulator that behaves like a Sungrow Logger1000A and the devices behind it.

Standard library only. Serves the same eight ports as the real Logger, shifted
by --base-port so it can never be mistaken for it (502-509 -> 15502-15509 by
default), each port answering for its own device's unit, exactly as
the register map records them.

Every register it serves has a known origin:
  - `data/synthetic/`: an invented site built from the integration's own field
    list (tools/make_synthetic.py), used when no recorded site is present;
  - or a recorded site (`data/register_map.json`, `data/seed_ha.json`, and survey
    dumps), kept only where the install it came from is.
A register with no known value is refused with exception 2 (illegal data
address), as the real Logger refuses the battery cell range. The simulator
never invents a number.

One shared "RS485 bus": a single lock, held for a per-request plus per-register
delay, so concurrent requests queue the way they do on the real Logger.
`--control <file.json>` is re-read on every request and can inject faults:
    {"timeout": ["15502/1"], "refuse": ["15503/2/input/5003"],
     "garbage": {"15502/1/input/5016": 65535}, "drop_every": 50}
Statistics are written to `--stats <file.json>` every 10 s.

    python sim/simulator.py --host 0.0.0.0 --base-port 15502
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import struct
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
READ_FNS = {3: "holding", 4: "input"}


class Bus:
    """The Logger's single RS485 bus: one transaction at a time."""

    def __init__(self, per_request_ms: float, per_register_ms: float) -> None:
        self.lock = asyncio.Lock()
        self.per_request = per_request_ms / 1000
        self.per_register = per_register_ms / 1000
        self.waiting = 0
        self.stats = {
            "requests": 0,
            "registers": 0,
            "busy_s": 0.0,
            "max_waiting": 0,
            "exceptions": 0,
            "timeouts": 0,
            "writes": 0,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    async def transact(self, registers: int) -> None:
        self.waiting += 1
        self.stats["max_waiting"] = max(self.stats["max_waiting"], self.waiting)
        async with self.lock:
            self.waiting -= 1
            hold = self.per_request + self.per_register * registers
            await asyncio.sleep(hold)
            self.stats["busy_s"] += hold
            self.stats["requests"] += 1
            self.stats["registers"] += registers


class Store:
    def __init__(self, regmap: dict, seed: dict, dumps: list[dict], base_port: int) -> None:
        self.units_by_port: dict[int, set[int]] = {}
        self.values: dict[tuple[int, int, str], dict[int, int]] = {}
        self.origin: dict[tuple[int, int, str, int], str] = {}
        for hub in regmap["hubs"]:
            port = base_port + int(hub["port"]) - 502
            for e in hub["entities"]:
                self.units_by_port.setdefault(port, set()).add(int(e["unit"]))
        for key, regs in seed["registers"].items():
            real_port, unit, space = key.split("/")
            port = base_port + int(real_port) - 502
            bucket = self.values.setdefault((port, int(unit), space), {})
            for addr, v in regs.items():
                bucket[int(addr)] = int(v["value"])
                self.origin[(port, int(unit), space, int(addr))] = v["from"]
        for dump in dumps:
            port, unit = base_port + dump["real_port"] - 502, dump["unit"]
            for space in ("input", "holding"):
                bucket = self.values.setdefault((port, unit, space), {})
                for addr, v in dump["registers"][space].items():
                    if int(addr) not in bucket and isinstance(v, int):
                        bucket[int(addr)] = v
                        self.origin[(port, unit, space, int(addr))] = dump["from"]

    #: where each kind keeps its serial number (input registers, ten words)
    SERIALS = (4989, 10710)

    def relayout(self, layout: dict[str, list], base_port: int) -> None:
        """Pretend to be another site: {"<real port>/<unit>": [port, unit]} moves a device, an absent one
        is gone. A list of [port, unit] pairs copies it: a bigger site from the recorded one, each copy with
        its own serial number (the last character raised by the copy's index), as real devices would have."""
        move: dict[tuple[int, int], tuple[int, int]] = {}
        copies: list[tuple[tuple[int, int], tuple[int, int], int]] = []
        for src, where in layout.items():
            rp, ru = (int(x) for x in src.split("/"))
            targets = where if where and isinstance(where[0], list) else [where]
            for k, (port, unit) in enumerate(targets):
                copies.append(((base_port + rp - 502, ru), (base_port + int(port) - 502, int(unit)), k))
        values: dict[tuple[int, int, str], dict[int, int]] = {}
        for source, target, k in copies:
            move.setdefault(source, target)
            for (p, u, sp), regs in self.values.items():
                if (p, u) != source:
                    continue
                regs = dict(regs)
                if k and sp == "input":
                    for first in self.SERIALS:
                        words = [a for a in range(first, first + 10) if regs.get(a)]
                        if words:  # the last word holding characters: its low byte is the last character
                            regs[words[-1]] = regs[words[-1]] + k
                values[(*target, sp)] = regs
        self._move = move
        self.values = values
        self.units_by_port = {}
        for _source, (p, u), _k in copies:
            self.units_by_port.setdefault(p, set()).add(u)
        others = len({t for _s, t, _k in copies if t[1] != 247})
        for (p, u, sp), regs in self.values.items():  # the Logger counts the devices this site has
            if u == 247 and sp == "input" and 8004 in regs:
                regs[8004] = others

    def follow(self, path: str | None, base_port: int) -> None:
        """Merge live values (written by sim/sink.py) when that file changes; checked at most twice a second."""
        self._live, self._live_base, self._live_mtime, self._live_checked = path, base_port, 0.0, 0.0

    def _refresh(self) -> None:
        path = getattr(self, "_live", None)
        if not path or time.monotonic() - self._live_checked < 0.5:
            return
        self._live_checked = time.monotonic()
        try:
            mtime = pathlib.Path(path).stat().st_mtime
            if mtime == self._live_mtime:
                return
            live = json.loads(pathlib.Path(path).read_text())
        except (OSError, ValueError):
            return
        self._live_mtime = mtime
        for key, regs in live.items():
            real_port, unit, space = key.split("/")
            pu = (self._live_base + int(real_port) - 502, int(unit))
            move = getattr(self, "_move", None)
            if move is not None:
                if pu not in move:
                    continue
                pu = move[pu]
            bucket = self.values.setdefault((*pu, space), {})
            for addr, v in regs.items():
                bucket[int(addr)] = int(v)

    def read(self, port: int, unit: int, space: str, addr: int, count: int) -> list[int] | None:
        self._refresh()
        bucket = self.values.get((port, unit, space), {})
        out = []
        for a in range(addr, addr + count):
            if a not in bucket:
                return None
            out.append(bucket[a])
        return out

    def write(self, port: int, unit: int, addr: int, values: list[int]) -> None:
        bucket = self.values.setdefault((port, unit, "holding"), {})
        for i, v in enumerate(values):
            bucket[addr + i] = v
            self.origin[(port, unit, "holding", addr + i)] = "written by a client"


def _control(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}


async def serve_port(port: int, store: Store, bus: Bus, args) -> asyncio.base_events.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        seen = 0
        try:
            while True:
                head = await reader.readexactly(7)
                tid, proto, length, unit = struct.unpack(">HHHB", head)
                pdu = await reader.readexactly(length - 1)
                fc = pdu[0]
                ctl = _control(args.control)
                seen += 1
                if ctl.get("drop_every") and seen % int(ctl["drop_every"]) == 0:
                    writer.close()
                    return
                if f"{port}/{unit}" in ctl.get("timeout", []):
                    bus.stats["timeouts"] += 1
                    continue  # never answer: the client must time out
                if unit not in store.units_by_port.get(port, set()):
                    reply = bytes([fc | 0x80, 0x0B])  # gateway target device failed to respond
                elif fc in READ_FNS:
                    addr, count = struct.unpack(">HH", pdu[1:5])
                    space = READ_FNS[fc]
                    await bus.transact(count)
                    refused = any(
                        f"{port}/{unit}/{space}/{a}" in ctl.get("refuse", [])
                        for a in range(addr, addr + count)
                    )
                    regs = None if refused else store.read(port, unit, space, addr, count)
                    if regs is None:
                        reply = bytes([fc | 0x80, 0x02])
                        bus.stats["exceptions"] += 1
                    else:
                        for a in range(addr, addr + count):
                            g = ctl.get("garbage", {}).get(f"{port}/{unit}/{space}/{a}")
                            if g is not None:
                                regs[a - addr] = int(g)
                        reply = bytes([fc, count * 2]) + struct.pack(f">{count}H", *regs)
                elif fc == 6:
                    addr, value = struct.unpack(">HH", pdu[1:5])
                    await bus.transact(1)
                    store.write(port, unit, addr, [value])
                    bus.stats["writes"] += 1
                    reply = pdu[:5]
                elif fc == 16:
                    addr, count, nbytes = struct.unpack(">HHB", pdu[1:6])
                    values = list(struct.unpack(f">{count}H", pdu[6 : 6 + nbytes]))
                    await bus.transact(count)
                    store.write(port, unit, addr, values)
                    bus.stats["writes"] += 1
                    reply = pdu[:5]
                else:
                    reply = bytes([fc | 0x80, 0x01])  # illegal function
                writer.write(struct.pack(">HHHB", tid, proto, len(reply) + 1, unit) + reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, args.host, port)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--base-port", type=int, default=15502)
    recorded = (ROOT / "data" / "seed_ha.json").exists()
    p.add_argument("--map", default=str(ROOT / "data" / ("register_map.json" if recorded else "synthetic/register_map.json")))
    p.add_argument("--seed", default=str(ROOT / "data" / ("seed_ha.json" if recorded else "synthetic/seed.json")))
    p.add_argument("--dumps", default=str(ROOT / "data" / "survey_dumps.json"))
    p.add_argument("--per-request-ms", type=float, default=40.0)
    p.add_argument("--per-register-ms", type=float, default=1.0)
    p.add_argument("--control", default=None)
    p.add_argument("--stats", default=None)
    p.add_argument("--live", default=None, help="file of live values to follow (sim/sink.py writes it)")
    p.add_argument("--layout", default=None, help='another site: JSON {"<real port>/<unit>": [port, unit]}; devices left out are gone')
    args = p.parse_args()
    regmap = json.loads(pathlib.Path(args.map).read_text())
    seed = json.loads(pathlib.Path(args.seed).read_text())
    dumps_path = pathlib.Path(args.dumps)
    dumps = json.loads(dumps_path.read_text()) if dumps_path.exists() else []
    store = Store(regmap, seed, dumps, args.base_port)
    if args.layout:
        store.relayout(json.loads(pathlib.Path(args.layout).read_text()), args.base_port)
    store.follow(args.live, args.base_port)
    bus = Bus(args.per_request_ms, args.per_register_ms)
    servers = [await serve_port(port, store, bus, args) for port in sorted(store.units_by_port)]
    print(
        f"serving {len(servers)} ports {sorted(store.units_by_port)} on {args.host}; "
        f"{sum(len(v) for v in store.values.values())} registers with a known origin",
        flush=True,
    )

    async def write_stats() -> None:
        while True:
            await asyncio.sleep(10)
            if args.stats:
                pathlib.Path(args.stats).write_text(json.dumps(bus.stats, indent=1))

    await asyncio.gather(write_stats(), *(s.serve_forever() for s in servers))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

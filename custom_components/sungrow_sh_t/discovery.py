"""Find what is on a Sungrow Logger: inverters, battery towers, the grid meter and the Logger itself.

Nothing about a site is assumed. Given the Logger's address and the ports to
try, discovery

1. finds the Logger (device address 247) and asks how many devices it has
   (`Total devices connected`, protocol 8005), so the search can stop once all
   are found;
2. tries each port and device address (low addresses first, where the Logger
   puts its forwarding addresses) and identifies what answers by its own model
   register: an inverter by 5000, a battery tower by 10710, a CHINT meter by a
   plausible phase voltage;
3. keeps one of each serial number, so a Logger that answers every address on
   every port, or one device on each port, comes out the same;
4. numbers inverters by port then address, and puts each tower with the
   inverter whose battery voltage it shares (a tower is wired to one inverter's
   battery), then by address.

`read(port, unit, space, address, count)` returns the registers, or raises
`ModbusError` (the device refused: it exists) or `ConnectionError` /
`TimeoutError` (nothing there). Every probe is a single read.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace

from . import fields as F
from .scheduler import ModbusError

Read = Callable[[int, int, str, int, int], Awaitable[list[int]]]
LOGGER_UNIT = 247
#: Modbus exceptions that mean "no such device behind this gateway"
NO_DEVICE = (0x0A, 0x0B)


@dataclass
class Found:
    kind: str
    port: int
    unit: int
    model: str | None = None
    serial: str | None = None
    battery_voltage: float | None = None


@dataclass
class Result:
    devices: list[F.Device] = field(default_factory=list)
    expected: int | None = None  # what the Logger says it has (all devices, its own excluded)
    probes: int = 0
    seconds: float = 0.0

    @property
    def complete(self) -> bool:
        found = sum(1 for d in self.devices if d.kind != "logger")
        return self.expected is None or found >= self.expected


class _Prober:
    def __init__(self, read: Read, deadline: float) -> None:
        self.read, self.deadline, self.probes = read, deadline, 0

    async def __call__(self, port: int, unit: int, space: str, address: int, count: int) -> list[int] | int | None:
        """The registers; the exception code if the device refused; None if nothing answered."""
        if time.monotonic() > self.deadline:
            raise TimeoutError("discovery took too long")
        self.probes += 1
        try:
            return list(await self.read(port, unit, space, address, count))
        except ModbusError as err:
            return None if err.code in NO_DEVICE else err.code
        except (ConnectionError, TimeoutError, OSError):
            return None


def _text(words: list[int]) -> str | None:
    v = F.decode_reg(F.Reg("input", 0, f"str{len(words)}"), words)
    return v.strip() if isinstance(v, str) and v.strip() else None


async def identify(probe: _Prober, port: int, unit: int) -> Found | None:
    """What answers at (port, unit), or None."""
    if unit == LOGGER_UNIT:
        r = await probe(port, unit, "input", 7999, 1)
        if isinstance(r, list) and r[0] in F.LOGGER_TYPE:
            return Found("logger", port, unit, F.LOGGER_TYPE[r[0]])
        return None
    r = await probe(port, unit, "input", 4999, 1)
    if r is None:
        return None  # no device: skip the other questions
    if isinstance(r, list):
        # an inverter by its model code; a model newer than this integration's list still counts when it
        # also answers with a serial number where an SH-T keeps it
        serial = await probe(port, unit, "input", 4989, 10)
        text = _text(serial) if isinstance(serial, list) else None
        if r[0] in F.DEVICE_TYPE or (text and r[0] not in (0, 0xFFFF)):
            volts = await probe(port, unit, "input", 13019, 1)
            return Found("inverter", port, unit, F.DEVICE_TYPE.get(r[0], f"unknown ({r[0]:#06x})"), text,
                         volts[0] / 10 if isinstance(volts, list) and 0 < volts[0] < 0xFFFF else None)
    r = await probe(port, unit, "input", 10709, 1)
    if isinstance(r, list):
        serial = await probe(port, unit, "input", 10710, 10)
        text = _text(serial) if isinstance(serial, list) else None
        if r[0] in F.TOWER_TYPE or (text and r[0] not in (0, 0xFFFF)):
            volts = await probe(port, unit, "input", 10740, 1)
            return Found("tower", port, unit, F.TOWER_TYPE.get(r[0], f"unknown ({r[0]:#06x})"), text,
                         volts[0] / 10 if isinstance(volts, list) and 0 < volts[0] < 0xFFFF else None)
    r = await probe(port, unit, "holding", 4358, 2)  # CHINT DTSU666: phase A voltage, 0.1 V, high word first
    if isinstance(r, list) and 500 <= (r[0] << 16 | r[1]) <= 4000:
        return Found("meter", port, unit, "DTSU666")
    return None


def arrange(found: list[Found]) -> list[F.Device]:
    """Number what was found: inverters by port and address; towers with their inverter, then by address."""
    inverters = sorted((f for f in found if f.kind == "inverter"), key=lambda f: (f.port, f.unit))
    devices = [F.device("inverter", i, f.port, f.unit, model=f.model, serial=f.serial) for i, f in enumerate(inverters, 1)]

    def home(t: Found) -> int:
        """The index of the inverter whose battery voltage the tower shares (within 3 %), else after all of them."""
        best, gap = len(inverters), 0.03
        for i, inv in enumerate(inverters):
            if t.battery_voltage and inv.battery_voltage:
                g = abs(t.battery_voltage - inv.battery_voltage) / inv.battery_voltage
                if g < gap:
                    best, gap = i, g
        return best

    towers = sorted((f for f in found if f.kind == "tower"), key=lambda t: (home(t), t.unit, t.port))
    devices += [
        F.device("tower", i, f.port, f.unit, model=f.model, serial=f.serial,
                 inverter=devices[home(f)].key if home(f) < len(inverters) else None)
        for i, f in enumerate(towers, 1)
    ]
    for kind in F.SINGLE:
        one = next((f for f in sorted(found, key=lambda f: (f.port, f.unit)) if f.kind == kind), None)
        if one:
            devices.append(F.device(kind, 0, one.port, one.unit, model=one.model))
    return devices


async def open_ports(host: str, ports: Iterable[int], timeout: float = 2.0) -> list[int]:
    """The ports that accept a connection at all (tried together, once each)."""

    async def one(port: int) -> int | None:
        try:
            _r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except (OSError, TimeoutError):
            return None
        w.close()
        return port

    return [p for p in await asyncio.gather(*(one(p) for p in ports)) if p is not None]


async def discover(
    read: Read, ports: Iterable[int], *, max_unit: int = 32, budget_s: float = 240.0, known: Iterable[tuple[int, int]] = ()
) -> Result:
    """Every device behind the Logger on `ports` (those that accept a connection), numbered (see `arrange`).

    `known`: (port, unit) of devices found before, asked first. A search again on a Logger that is
    busy with this integration's own polling then finds them in seconds and stops at the Logger's
    count, rather than walking every address first (9 Nov 2026: the meter missed a 240 s limit)."""
    started = time.monotonic()
    probe = _Prober(read, started + budget_s)
    ports = list(ports)
    result = Result()
    found: list[Found] = []
    seen: set[tuple[str, str]] = set()

    def keep(f: Found) -> None:
        tag = (f.kind, f.serial or f"{f.port}/{f.unit}" if f.kind in ("inverter", "tower") else f.kind)
        if tag not in seen:
            seen.add(tag)
            found.append(f)

    try:
        for port in ports:  # the Logger first: it says how many to look for
            logger = await identify(probe, port, LOGGER_UNIT)
            if logger:
                keep(logger)
                total = await probe(port, LOGGER_UNIT, "input", 8004, 1)
                if isinstance(total, list) and 0 < total[0] < 256:
                    result.expected = total[0]
                break
        others = lambda: sum(1 for f in found if f.kind != "logger")
        short = lambda: result.expected is not None and others() < result.expected
        first = min(max_unit, (result.expected or 8) + 2)
        unanswered: list[tuple[int, int]] = []
        for port, unit in dict.fromkeys(k for k in known if k[1] != LOGGER_UNIT and k[0] in ports):
            if not short() and result.expected is not None:
                break
            f = await identify(probe, port, unit) or await identify(probe, port, unit)  # busy once: asked again now
            if f:
                keep(f)
        for units in (range(1, first + 1), range(first + 1, max_unit + 1)):
            for unit in units:
                for port in ports:
                    if result.expected is not None and others() >= result.expected:
                        break
                    f = await identify(probe, port, unit)
                    if f:
                        keep(f)
                    elif unit <= first:
                        unanswered.append((port, unit))
        # Fewer than the Logger counts: a device busy with another client can miss one question (9 Nov 2026,
        # the meter on the first real search), so each address of the first pass that gave nothing is asked
        # once more before giving up.
        for port, unit in unanswered:
            if not short():
                break
            f = await identify(probe, port, unit)
            if f:
                keep(f)
    except TimeoutError:
        pass  # keep what was found in time
    result.devices = arrange(found)
    result.probes = probe.probes
    result.seconds = round(time.monotonic() - started, 1)
    return result


def merge(previous: list[F.Device], found: list[F.Device]) -> tuple[list[F.Device], list[str], list[str]]:
    """A new search over an old one: (the devices to keep, the keys that are new, the keys not found this time).

    A device found before keeps its key and name, so its entities keep their ids. It is matched by serial
    number, or, when the old record has none (a move from YAML records none), by its kind and its address
    on the Logger's bus, which no two devices share. A new device is numbered after the highest of its kind.
    One not found this time is kept as it was: a busy or switched-off device is not a removed one.
    A tower keeps the inverter the search put it with, under that inverter's kept key."""
    def serial(d: F.Device) -> tuple[str, str] | None:
        return (d.kind, d.serial) if d.serial and d.kind not in F.SINGLE else None

    def place(d: F.Device) -> tuple[str, str]:
        return (d.kind, d.kind) if d.kind in F.SINGLE else (d.kind, f"unit {d.unit}")

    by_serial = {serial(d): d for d in previous if serial(d)}
    by_place = {place(d): d for d in previous if d.kind in F.SINGLE or not d.serial}
    used: dict[str, set[int]] = {}
    for d in previous:
        if d.kind not in F.SINGLE:
            used.setdefault(d.kind, set()).add(int(d.key.rsplit("_", 1)[1]))
    out: list[F.Device] = []
    renamed: dict[str, str] = {}
    matched: set[str] = set()
    new: list[str] = []
    for d in found:
        before = by_serial.get(serial(d)) if serial(d) else None
        before = before or by_place.get(place(d))
        if before and before.key not in matched:
            matched.add(before.key)
            # a model recorded more exactly before (DTSU666-20 over the DTSU666 a search can tell) is kept
            model = before.model if before.model and (not d.model or before.model.startswith(d.model)) else d.model
            kept = F.Device(before.key, d.kind, d.port, d.unit, before.name, model,
                            d.serial or before.serial, d.inverter)
        elif d.kind in F.SINGLE:
            kept = d
            new.append(d.key)
        else:
            n = max(used.get(d.kind, {0}) | {0}) + 1
            used.setdefault(d.kind, set()).add(n)
            kept = F.device(d.kind, n, d.port, d.unit, model=d.model, serial=d.serial, inverter=d.inverter)
            new.append(kept.key)
        renamed[d.key] = kept.key
        out.append(kept)
    had = {d.key: d.inverter for d in previous}
    # a tower follows its inverter's kept key; one found without an inverter keeps the one it had
    out = [replace(d, inverter=renamed.get(d.inverter, d.inverter) if d.inverter else had.get(d.key)) if d.kind == "tower" else d
           for d in out]
    missing = [d.key for d in previous if d.key not in matched and d.key not in {o.key for o in out}]
    out += [d for d in previous if d.key in missing]
    return out, new, missing


def keep_keys(previous: list[F.Device], found: list[F.Device]) -> list[F.Device]:
    """`merge`'s devices: every device to keep, under its old key where it had one."""
    return merge(previous, found)[0]

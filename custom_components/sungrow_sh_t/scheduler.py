"""One worker for the whole Logger: the bus is never asked two things at once.

- **Earliest deadline first.** Each block from the planner has a due time; the
  worker always serves the most overdue one, so a busy minute delays every
  block a little instead of starving one.
- **Writes jump the queue.** A write waits only for the request already on
  the bus, then is read back; the result is the read-back, never the request.
- **Self-healing plan.** A merged block that is refused twice in a row is split
  into its own reads and the join is remembered, so it is never merged again
  this run. A single read refused 3 times is backed off (1 min, doubling to
  1 h) instead of being asked for every cycle, the way the YAML hammered the
  battery cell registers.
- **Transient refusals retried once.** Holding registers behind the Logger are
  sometimes refused while it refreshes them (7 Nov survey: "intermittent");
  one retry after a short pause, then the failure counts.
- **One connection per port, kept open,** reconnected with back-off.

Own minimal Modbus TCP client on asyncio streams: no pymodbus, so no clash
with Home Assistant's own modbus integration or its pinned version.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .planner import Block, split

_LOGGER = logging.getLogger(__name__)

FC = {"holding": 3, "input": 4}
RETRY_PAUSE = 0.3
BACKOFF_START = 60.0
BACKOFF_MAX = 3600.0
#: a device that times out this many times running is asked only every SILENT_START s (doubling up to
#: SILENT_MAX): a missing device must not hold the shared bus with a timeout every few seconds
SILENT_AFTER = 2
SILENT_START = 30.0
SILENT_MAX = 60.0


class ModbusError(Exception):
    """The device answered with a Modbus exception."""

    def __init__(self, code: int) -> None:
        super().__init__(f"Modbus exception {code}")
        self.code = code


class Port:
    """One kept-open TCP connection to one Logger port."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self._r: asyncio.StreamReader | None = None
        self._w: asyncio.StreamWriter | None = None
        self._tid = itertools.count(1)
        self.retry_at = 0.0
        self._delay = 1.0

    async def request(self, unit: int, pdu: bytes) -> bytes:
        if self._w is None:
            if time.monotonic() < self.retry_at:
                raise ConnectionError(f"port {self.port} backing off")
            try:
                self._r, self._w = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), self.timeout
                )
                self._delay = 1.0
            except (OSError, TimeoutError) as err:
                self.retry_at = time.monotonic() + self._delay
                self._delay = min(self._delay * 2, 60.0)
                raise ConnectionError(str(err)) from err
        tid = next(self._tid) & 0xFFFF
        try:
            self._w.write(struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit) + pdu)
            await self._w.drain()
            while True:
                head = await asyncio.wait_for(self._r.readexactly(7), self.timeout)
                rtid, _, length, _ = struct.unpack(">HHHB", head)
                body = await asyncio.wait_for(self._r.readexactly(length - 1), self.timeout)
                if rtid == tid:
                    break  # a late answer to an earlier, timed-out request is discarded
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
            self.close()
            raise ConnectionError(str(err) or type(err).__name__) from err
        if body[0] & 0x80:
            raise ModbusError(body[1])
        return body

    def close(self) -> None:
        if self._w is not None:
            self._w.close()
        self._r = self._w = None


class OwnTransport:
    """This integration's own Modbus TCP client: one kept-open connection per port.

    Used where Home Assistant has no shared Modbus connections (before 2026.11);
    `ha_transport.HaTransport` replaces it where it does.
    """

    def __init__(self, host: str, timeout: float) -> None:
        self.host, self.timeout = host, timeout
        self.ports: dict[int, Port] = {}

    def _port(self, port: int) -> Port:
        if port not in self.ports:
            self.ports[port] = Port(self.host, port, self.timeout)
        return self.ports[port]

    async def read(self, port: int, unit: int, space: str, address: int, count: int) -> list[int]:
        body = await self._port(port).request(unit, struct.pack(">BHH", FC[space], address, count))
        if len(body) < 2 + 2 * count or body[1] != 2 * count:  # a short or garbled answer: as if lost
            self._port(port).close()
            raise ConnectionError(f"port {port} unit {unit}: answer of {len(body)} bytes for {count} registers")
        return list(struct.unpack(f">{count}H", body[2 : 2 + 2 * count]))

    async def write(self, port: int, unit: int, address: int, values: list[int]) -> None:
        if len(values) == 1:
            pdu = struct.pack(">BHH", 6, address, values[0])
        else:
            n = len(values)
            pdu = struct.pack(f">BHHB{n}H", 16, address, n, 2 * n, *values)
        await self._port(port).request(unit, pdu)

    def close(self) -> None:
        for p in self.ports.values():
            p.close()


@dataclass(order=True)
class _Due:
    due: float
    seq: int
    block: Block = field(compare=False)


@dataclass
class Stats:
    requests: int = 0
    registers: int = 0
    refusals: int = 0
    timeouts: int = 0
    splits: int = 0
    writes: int = 0
    busy_s: float = 0.0
    started: float = field(default_factory=time.monotonic)

    def busy_fraction(self) -> float:
        return self.busy_s / max(time.monotonic() - self.started, 1e-9)


@dataclass
class _Write:
    port: int
    unit: int
    address: int
    values: list[int] | None  # None: a read on request (count registers of space)
    done: asyncio.Future
    space: str = "holding"
    count: int = 0


class Scheduler:
    """Runs the plan. `on_data(block_reads, registers_by_address, read_at)` gets every answer."""

    def __init__(
        self,
        host: str,
        blocks: list[Block],
        on_data: Callable[[Block, dict[int, int], float], None],
        *,
        timeout: float = 3.0,
        gap: float = 0.02,
        fast_max: float = 2.0,
        transport=None,
    ) -> None:
        self.host, self.on_data, self.timeout, self.gap = host, on_data, timeout, gap
        self.transport = transport or OwnTransport(host, timeout)
        self.stats = Stats()
        self._seq = itertools.count()
        self._heap: list[_Due] = []
        self._writes: asyncio.Queue[_Write] = asyncio.Queue()
        self._wake = asyncio.Event()
        self._fails: dict[tuple, int] = {}
        self._silent: dict[tuple[int, int], int] = {}  # (port, unit) -> timeouts running
        self._silent_next: dict[tuple[int, int], float] = {}  # a quiet device: when the next block may ask it
        self._backoff: dict[tuple, float] = {}
        self._boost: tuple[float, float] = (0.0, 0.0)
        self._fast_max = fast_max
        now = time.monotonic()
        for b in blocks:
            self._push(b, now)

    # --- public -----------------------------------------------------------

    def set_blocks(self, blocks: list[Block]) -> None:
        """A new plan: every block due now (each is read in turn), refusals forgotten."""
        now = time.monotonic()
        self._heap = []
        self._fails.clear()
        self._backoff.clear()
        for b in blocks:
            self._push(b, now)
        self._wake.set()

    def boost(self, interval: float, seconds: float) -> None:
        """Poll the fast lane every `interval` s for the next `seconds` (after a command)."""
        self._boost = (interval, time.monotonic() + seconds)
        now = time.monotonic()
        for d in self._heap:  # bring the fast lane forward now, not at its next turn
            if d.block.interval <= self._fast_max and d.due > now + interval:
                d.due = now + interval
        import heapq

        heapq.heapify(self._heap)
        self._wake.set()

    def _interval(self, b: Block) -> float:
        interval, until = self._boost
        if b.interval <= self._fast_max and time.monotonic() < until:
            return min(b.interval, interval)
        return b.interval

    async def write(self, port: int, unit: int, address: int, values: list[int]) -> list[int]:
        """Write holding registers, then read them back; returns the read-back."""
        fut = asyncio.get_running_loop().create_future()
        self._writes.put_nowait(_Write(port, unit, address, values, fut))
        self._wake.set()
        return await fut

    async def read_now(self, port: int, unit: int, space: str, address: int, count: int) -> list[int]:
        """Read a span ahead of the plan (an entity asked for a refresh); queued like a write."""
        fut = asyncio.get_running_loop().create_future()
        self._writes.put_nowait(_Write(port, unit, address, None, fut, space, count))
        self._wake.set()
        return await fut

    async def run(self) -> None:
        import heapq

        while True:
            if not self._writes.empty():
                await self._do_write(self._writes.get_nowait())
                continue
            if not self._heap:
                await self._wait(None)
                continue
            first = self._heap[0]
            delay = first.due - time.monotonic()
            if delay > 0:
                await self._wait(delay)
                continue
            heapq.heappop(self._heap)
            quiet_until = self._silent_next.get((first.block.port, first.block.unit), 0.0)
            if quiet_until > time.monotonic():  # one block asks a quiet device for all of them
                self._push(first.block, quiet_until + 0.5)
                continue
            try:
                await self._do_read(first.block)
            except asyncio.CancelledError:
                raise
            except Exception:  # the loop must never die: log, retry the block later
                _LOGGER.exception("reading %s", first.block)
                self._push(first.block, time.monotonic() + max(first.block.interval, 5))
            await asyncio.sleep(self.gap)

    def close(self) -> None:
        self.transport.close()

    # --- internals --------------------------------------------------------

    def _push(self, block: Block, due: float) -> None:
        import heapq

        heapq.heappush(self._heap, _Due(due, next(self._seq), block))

    async def _wait(self, delay: float | None) -> None:
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), delay)
        except TimeoutError:
            pass

    async def _bus(self, coro, registers: int):
        t = time.monotonic()
        try:
            return await coro
        finally:
            self.stats.busy_s += time.monotonic() - t
            self.stats.requests += 1
            self.stats.registers += registers

    async def _read(self, b: Block) -> list[int]:
        for attempt in (0, 1):
            try:
                return await self._bus(self.transport.read(b.port, b.unit, b.space, b.address, b.count), b.count)
            except ModbusError as err:
                self.stats.refusals += 1
                if attempt or err.code != 2:
                    raise
                await asyncio.sleep(RETRY_PAUSE)
        raise AssertionError("unreachable")

    async def _do_read(self, b: Block) -> None:
        key = (b.port, b.unit, b.space, b.address, b.count)
        now = time.monotonic()
        try:
            regs = await self._read(b)
        except ModbusError:
            self._fails[key] = self._fails.get(key, 0) + 1
            if len(b.reads) > 1 and self._fails[key] >= 2:
                parts = split(b)
                self.stats.splits += 1
                _LOGGER.warning(
                    "%s/%s %s %s+%s refused when merged; split into %d",
                    b.port, b.unit, b.space, b.address, b.count, len(parts),
                )
                for p in parts:
                    self._push(p, time.monotonic())
                return
            if self._fails[key] >= 3:
                wait = min(self._backoff.get(key, BACKOFF_START / 2) * 2, BACKOFF_MAX)
                self._backoff[key] = wait
                self._push(b, now + wait)
                return
            self._push(b, now + self._interval(b))
            return
        except ConnectionError:
            self.stats.timeouts += 1
            dev = (b.port, b.unit)
            n = self._silent.get(dev, 0) + 1
            self._silent[dev] = n
            wait = min(self._interval(b), 5)
            if n >= SILENT_AFTER:  # this device has gone quiet: ask it rarely until it answers again
                wait = max(wait, min(SILENT_START * 2 ** (n - SILENT_AFTER), SILENT_MAX))
                self._silent_next[dev] = now + wait
                if n == SILENT_AFTER:
                    _LOGGER.warning("port %s unit %s stopped answering; asking it every %d-%d s until it does", b.port, b.unit, SILENT_START, SILENT_MAX)
            self._push(b, now + wait)
            return
        self._silent_next.pop((b.port, b.unit), None)
        if self._silent.pop((b.port, b.unit), 0) >= SILENT_AFTER:
            _LOGGER.warning("port %s unit %s answers again", b.port, b.unit)
        self._fails.pop(key, None)
        self._backoff.pop(key, None)
        self._push(b, now + self._interval(b))
        self.on_data(b, {b.address + i: v for i, v in enumerate(regs)}, time.time())

    async def _do_write(self, w: _Write) -> None:
        if w.values is None:
            try:
                w.done.set_result(await self._read(Block(w.port, w.unit, w.space, w.address, w.count, 0)))
            except Exception as err:  # noqa: BLE001 - handed to the caller
                if not w.done.done():
                    w.done.set_exception(err)
            return
        try:
            await self._bus(self.transport.write(w.port, w.unit, w.address, w.values), len(w.values))
            self.stats.writes += 1
            back = Block(w.port, w.unit, "holding", w.address, len(w.values), 0)
            w.done.set_result(await self._read(back))
        except Exception as err:  # noqa: BLE001 - handed to the caller
            if not w.done.done():
                w.done.set_exception(err)

"""The hub: one scheduler for the whole Logger, and the latest value of every field.

Fields name registers; the hub turns every register a field needs into a read,
lets the planner merge them, runs the scheduler, and on each answer works out
only the fields whose registers changed. An entity is told only when its value
actually changed, so nothing writes a state (or a database row) for a value
that stayed the same.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from . import fields as F
from .planner import EVERYTHING, Read, gaps, plan
from .scheduler import ModbusError, Scheduler

_LOGGER = logging.getLogger(__name__)

FAST = 2  # seconds: battery, grid, solar and house power
BOOST = 1  # seconds, for BOOST_FOR after any command
BOOST_FOR = 30
INTERVALS = {**F.TIERS, "fast": FAST}
#: "gentle" pace: every interval this many times longer and no boost (alongside another Modbus client)
GENTLE = 10

Word = tuple[int, int, str, int]  # (port, unit, space, address)


class ReadOnlyError(Exception):
    """A write while the integration is set to read only."""

Key = tuple[str, str]  # (device, field key)


Span = tuple[int, int, str, int, int]  # (port, unit, space, address, count)


def expand(spans: list[Span]) -> set[tuple[int, int, str, int]]:
    """Registers from spans: the saved form of what this Logger has answered."""
    return {(p, u, s, a + i) for p, u, s, a, n in spans for i in range(n)}


class Hub:
    def __init__(
        self,
        host: str,
        devices: list[F.Device],
        transport=None,
        *,
        extra_reads: list[tuple[int, int, str, int, int, int]] = (),
        gentle: bool = False,
        read_only: bool = False,
        own_entities: bool = True,
        readable: list[Span] = (),
        unreadable: list[Span] = (),
    ) -> None:
        """`extra_reads`: (port, unit, space, address, count, interval) spans someone else needs
        (the YAML entities this integration stands in for), read at their own interval.
        `own_entities` False: read only those (this integration's own fields stay unread)."""
        self.host = host
        self.kinds: dict[str, str] = {d.key: d.kind for d in devices}
        self.device_list: list[F.Device] = list(devices)  # as the entry records them (devices.py shows them)
        self.gentle, self.read_only = gentle, read_only
        self.legacy = None  # the YAML package this hub stands in for, if any (set by the integration)
        self.pace = GENTLE if gentle else 1
        self.word_at: dict[Word, float] = {}
        self._word_listeners: list[Callable[[set[Word]], None]] = []
        self.values: dict[Key, Any] = {}
        self.read_at: dict[Key, float] = {}
        self.words: dict[tuple[int, int, str, int], int] = {}
        self._listeners: dict[Key, list[Callable[[], None]]] = defaultdict(list)
        self._fresh_listeners: dict[Key, list[Callable[[], None]]] = defaultdict(list)
        self._was_fresh: dict[Key, bool] = {}
        self._by_word: dict[tuple[int, int, str, int], set[Key]] = defaultdict(set)
        self.fields: dict[Key, F.Field] = {}
        self.devices: dict[str, tuple[int, int, str]] = {}
        reads: dict[tuple, Read] = {}
        for dev, (port, unit, name, flds) in F.table(devices).items():
            self.devices[dev] = (port, unit, name)
            for f in flds if own_entities else ():
                self.fields[(dev, f.key)] = f
                for r in f.regs:
                    interval = INTERVALS[f.tier] * (self.pace if f.tier != "static" else 1)
                    if self.kinds[dev] == "inverter" and r.space == "holding":
                        # protocol 1.2(6): settings must not be polled often through the Logger
                        interval = max(interval, INTERVALS["setting"])
                    rk = (port, unit, r.space, r.address, r.count)
                    old = reads.get(rk)
                    if old is None or interval < old.interval:
                        reads[rk] = Read(f"{port}/{unit}/{r.space}/{r.address}+{r.count}", port, unit, r.space, r.address, r.count, interval)
                    for i in range(r.count):
                        self._by_word[(port, unit, r.space, r.address + i)].add((dev, f.key))
        for port, unit, space, address, count, interval in extra_reads:
            interval = interval * self.pace
            rk = (port, unit, space, address, count)
            old = reads.get(rk)
            if old is None or interval < old.interval:
                reads[rk] = Read(f"{port}/{unit}/{space}/{address}+{count}", port, unit, space, address, count, interval)
        self._reads = list(reads.values())
        self.readable: list[Span] = list(readable)  # learned on this install (survey), saved by the integration
        self.unreadable: list[Span] = list(unreadable)
        self.blocks = plan(self._reads, expand(self.readable))
        self.scheduler = Scheduler(host, self.blocks, self._on_data, transport=transport)
        self._task: asyncio.Task | None = None

    # --- lifecycle --------------------------------------------------------

    def start(self, create_task: Callable) -> None:
        self._task = create_task(self.scheduler.run())
        self._watch = create_task(self.watch_freshness())

    def survey_todo(self) -> list[Span]:
        """Gaps a fully known Logger would read across, not yet tried on this one."""
        tried = expand(self.readable) | expand(self.unreadable)
        return [g for g in gaps(plan(self._reads, EVERYTHING)) if not all((g[0], g[1], g[2], g[3] + i) in tried for i in range(g[4]))]

    async def survey(self, pause: float = 1.0) -> bool:
        """Ask the Logger for each untried gap, one at a time between the plan's own reads; re-plan with
        what answered. True when every gap has been tried (False: the link dropped, try again later)."""
        todo = self.survey_todo()
        for port, unit, space, address, count in todo:
            try:
                await self.scheduler.read_now(port, unit, space, address, count)
            except ModbusError:
                self.unreadable.append((port, unit, space, address, count))
            except (ConnectionError, TimeoutError, OSError):
                return False
            else:
                self.readable.append((port, unit, space, address, count))
            await asyncio.sleep(pause * self.pace)
        if todo:
            self.replan()
        return True

    def replan(self) -> None:
        """Merge reads across every gap this Logger has proven readable."""
        self.blocks = plan(self._reads, expand(self.readable))
        self.scheduler.set_blocks(self.blocks)

    async def stop(self) -> None:
        for t in (self._task, getattr(self, "_watch", None)):
            if t:
                t.cancel()
        self.scheduler.close()

    # --- entities ---------------------------------------------------------

    def listen(self, key: Key, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners[key].append(cb)
        return lambda: self._listeners[key].remove(cb)

    def listen_freshness(self, key: Key, cb: Callable[[], None]) -> Callable[[], None]:
        """Called when `key` turns fresh or stale without its value changing."""
        self._fresh_listeners[key].append(cb)
        return lambda: self._fresh_listeners[key].remove(cb)

    async def watch_freshness(self) -> None:
        """Every 15 s, tell entities whose freshness flipped (a value that stops arriving goes unavailable)."""
        while True:
            await asyncio.sleep(15)
            for key, cbs in list(self._fresh_listeners.items()):
                fresh = self.is_fresh(key)
                if self._was_fresh.get(key) == fresh:
                    continue
                self._was_fresh[key] = fresh
                for cb in list(cbs):
                    try:
                        cb()
                    except Exception:
                        _LOGGER.exception("availability of %s", key)

    def is_fresh(self, key: Key) -> bool:
        """False once a value is older than three of its intervals (and 30 s)."""
        at = self.read_at.get(key)
        if at is None:
            return False
        limit = max(3 * INTERVALS[self.fields[key].tier] * self.pace, 30)
        return time.time() - at < limit

    def listen_words(self, cb: Callable[[set[Word]], None]) -> Callable[[], None]:
        """Called with the registers a write or a requested read just brought back."""
        self._word_listeners.append(cb)
        return lambda: self._word_listeners.remove(cb)

    def read_words(self, port: int, unit: int, space: str, address: int, count: int) -> tuple[list[int] | None, float | None]:
        """The latest words of a span and when the oldest of them was read (None if any is missing)."""
        keys = [(port, unit, space, address + i) for i in range(count)]
        if any(k not in self.words for k in keys):
            return None, None
        return [self.words[k] for k in keys], min(self.word_at[k] for k in keys)

    async def read_now(self, port: int, unit: int, space: str, address: int, count: int) -> None:
        """Read a span now, ahead of its turn (an entity was asked to update)."""
        regs = await self.scheduler.read_now(port, unit, space, address, count)
        self._store(port, unit, space, {address + i: v for i, v in enumerate(regs)}, time.time(), notify=True)

    def field_value(self, dev: str, key: str):
        return self.values.get((dev, key))

    async def write_many(self, dev: str, writes: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
        """Write several single registers in order; returns (address, asked, read back) for each."""
        out = []
        for address, value in writes:
            back = await self.write(dev, address, [value])
            out.append((address, value, back[0] if back else None))
        return out

    async def write(self, dev: str, address: int, values: list[int]) -> list[int]:
        """Write holding registers on a device, boost the fast lane, return the read-back."""
        port, unit, _ = self.devices[dev]
        return await self.write_port(port, unit, address, values)

    async def write_port(self, port: int, unit: int, address: int, values: list[int]) -> list[int]:
        """Write holding registers by port and unit (as a YAML hub names them); return the read-back."""
        if self.read_only:
            raise ReadOnlyError("the Sungrow integration is set to read only (Configure)")
        if not self.gentle:
            self.scheduler.boost(BOOST, BOOST_FOR)
        back = await self.scheduler.write(port, unit, address, values)
        self._store(port, unit, "holding", {address + i: v for i, v in enumerate(back)}, time.time(), notify=True)
        return back

    # --- data -------------------------------------------------------------

    def _on_data(self, block, regs: dict[int, int], read_at: float) -> None:
        self._store(block.port, block.unit, block.space, regs, read_at)

    def _store(self, port: int, unit: int, space: str, regs: dict[int, int], read_at: float, notify: bool = False) -> None:
        touched: set[Key] = set()
        for addr, w in regs.items():
            wk = (port, unit, space, addr)
            changed = self.words.get(wk) != w
            self.words[wk] = w  # every word read, for the entities that decode words themselves
            self.word_at[wk] = read_at
            keys = self._by_word.get(wk)
            if not keys:
                continue
            for k in keys:
                self.read_at[k] = read_at  # read, even if unchanged
            if changed:
                touched |= keys
        for key in touched:
            self._recompute(key, port, unit)
        if notify and self._word_listeners:
            words = {(port, unit, space, a) for a in regs}
            for cb in list(self._word_listeners):
                try:
                    cb(words)
                except Exception:  # one entity must never stop the polling
                    _LOGGER.exception("updating after a command")

    def _recompute(self, key: Key, port: int, unit: int) -> None:
        f = self.fields[key]
        decoded = []
        for r in f.regs:
            w = [self.words.get((port, unit, r.space, r.address + i)) for i in range(r.count)]
            decoded.append(None if None in w else F.decode_reg(r, w))
        try:
            v = F.value(f, decoded)
        except (ArithmeticError, TypeError, ValueError) as err:
            _LOGGER.debug("%s: %s", key, err)
            v = None
        if self.values.get(key, object()) == v:
            return
        self.values[key] = v
        for cb in list(self._listeners.get(key, ())):
            try:
                cb()
            except Exception:  # one entity must never stop the polling
                _LOGGER.exception("updating %s", key)

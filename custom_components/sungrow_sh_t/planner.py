"""Plan the fewest, cheapest Modbus requests that cover every read.

The YAML asks the Logger for each sensor separately, on its own timer, from
eight independent clients. This module turns the same reads into a request
plan for one shared bus:

- **Merged blocks.** Reads on the same port, unit and register space are
  joined into one request when the registers between them are *proven*
  readable on this Logger (learned per install, see hub.survey). The Logger
  refuses a whole request if any one register in it is unsupported, so an
  unproven gap is never bridged.
- **Duplicates removed.** A read that lies inside another (the YAML reads
  tower current 10741 again although 10709+40 already covers it) costs nothing.
- **A cost model, not a rule of thumb.** Every request costs a fixed bus time
  plus a time per register, paid as often as the block is polled. Two blocks
  are merged only when the merged block costs less per minute than the two
  apart, so a slow read is not dragged into a fast block when that would cost
  more than it saves.
- **Identity read once.** Serial numbers, device type and ratings do not
  change; they are read at start and then hourly, not every 10 s.

Pure Python, no Home Assistant import.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

#: The Logger takes at most 125 registers per request; stay well under it so
#: one refused register costs less to find.
MAX_BLOCK = 100

#: Read once at start, then at this interval (seconds).
STATIC_INTERVAL = 3600
STATIC_IDS = frozenset(
    {
        "sg_inverter_serial_inv1",
        "sg_dev_code_inv1",
        "sg_inverter_rated_output_inv1",
        "sg_inverter_serial_inv2",
        "sg_dev_code_inv2",
        "sg_inverter_rated_output_inv2",
        "logger_dev_code",
        "logger_total_nominal_active_power",
        "logger_total_battery_rated_capacity",
        "logger_max_total_nominal_active_power",
    }
)

#: Measured through this Logger (8 Nov 2026): about 58 ms per round trip for
#: a short read. Split into a fixed and a per-register part for the cost model.
REQUEST_MS = 56.0
REGISTER_MS = 1.0


@dataclass(frozen=True)
class Read:
    """One value the integration needs: a register span and how fresh it must be."""

    key: str
    port: int
    unit: int
    space: str  # "input" or "holding"
    address: int
    count: int
    interval: int

    @property
    def end(self) -> int:
        return self.address + self.count


@dataclass
class Block:
    """One Modbus request in the plan."""

    port: int
    unit: int
    space: str
    address: int
    count: int
    interval: int
    reads: list[Read] = field(default_factory=list)

    @property
    def end(self) -> int:
        return self.address + self.count

    def cost(self) -> float:
        """Bus milliseconds per minute this block costs."""
        return 60 / self.interval * (REQUEST_MS + REGISTER_MS * self.count)


def reads_from_map(regmap: dict, spec_registers) -> list[Read]:
    """The reads the YAML makes, one per entity; `spec_registers(entry)` gives its length."""
    out = []
    for hub in regmap["hubs"]:
        for e in hub["entities"]:
            interval = int(e.get("scan_interval", 15))
            if e["unique_id"] in STATIC_IDS:
                interval = STATIC_INTERVAL
            out.append(
                Read(
                    key=e["unique_id"],
                    port=int(hub["port"]),
                    unit=int(e["unit"]),
                    space=e["input_type"],
                    address=int(e["address"]),
                    count=spec_registers(e),
                    interval=interval,
                )
            )
    return out


def plan(
    reads: Iterable[Read],
    readable: set[tuple[int, int, str, int]] | Everything,
    *,
    no_merge: set[tuple[int, str, int]] | frozenset = frozenset(),
) -> list[Block]:
    """Merge reads into blocks.

    `readable` holds (port, unit, space, address) proven to answer (or
    `EVERYTHING`, to see which gaps a merge would need). `no_merge` holds
    (port, unit, space, address) of block starts that were refused when merged
    at runtime; a read starting there is never joined to the block before it.
    """
    groups: dict[tuple[int, int, str], list[Read]] = {}
    for r in reads:
        groups.setdefault((r.port, r.unit, r.space), []).append(r)
    blocks: list[Block] = []
    for (port, unit, space), rs in sorted(groups.items()):
        rs.sort(key=lambda r: (r.address, -r.count))
        cur: Block | None = None
        for r in rs:
            if cur is not None and _joinable(cur, r, port, unit, space, readable, no_merge):
                merged = Block(
                    port,
                    unit,
                    space,
                    cur.address,
                    max(cur.end, r.end) - cur.address,
                    min(cur.interval, r.interval),
                    [*cur.reads, r],
                )
                alone = Block(port, unit, space, r.address, r.count, r.interval)
                if r.end <= cur.end or merged.cost() <= cur.cost() + alone.cost():
                    cur = merged
                    continue
            if cur is not None:
                blocks.append(cur)
            cur = Block(port, unit, space, r.address, r.count, r.interval, [r])
        if cur is not None:
            blocks.append(cur)
    return blocks


class Everything:
    """A `readable` that contains every register: plans the merges a fully known Logger would allow."""

    def __contains__(self, _key: object) -> bool:
        return True


EVERYTHING = Everything()


def _joinable(cur: Block, r: Read, port: int, unit: int, space: str, readable, no_merge) -> bool:
    if (port, unit, space, r.address) in no_merge:
        return False
    if max(cur.end, r.end) - cur.address > MAX_BLOCK:
        return False
    return all((port, unit, space, a) in readable for a in range(cur.end, r.address))


def gaps(blocks: list[Block]) -> list[tuple[int, int, str, int, int]]:
    """(port, unit, space, address, count) of every stretch inside a block that none of its reads covers."""
    out = []
    for b in blocks:
        covered = sorted((r.address, r.end) for r in b.reads)
        pos = b.address
        for start, end in covered:
            if start > pos:
                out.append((b.port, b.unit, b.space, pos, start - pos))
            pos = max(pos, end)
    return out


def split(block: Block) -> list[Block]:
    """A refused merged block, halved by its reads (a binary search for the bad register).

    Each half spans only its own reads; a half that is refused again is halved
    again, so one bad register in a 25-read block is isolated in about five
    steps. A single read cannot be split and is returned as it is.
    """
    rs = sorted(block.reads, key=lambda r: (r.address, -r.count))
    if len(rs) <= 1:
        return [block]
    halves = (rs[: len(rs) // 2], rs[len(rs) // 2 :])
    out = []
    for h in halves:
        start = min(r.address for r in h)
        out.append(
            Block(
                block.port, block.unit, block.space, start,
                max(r.end for r in h) - start, min(r.interval for r in h), list(h),
            )
        )
    return out


def load_per_minute(blocks: Iterable[Block]) -> tuple[float, float]:
    """(requests per minute, bus busy fraction) for a plan."""
    req = sum(60 / b.interval for b in blocks)
    busy = sum(b.cost() for b in blocks) / 60000
    return req, busy

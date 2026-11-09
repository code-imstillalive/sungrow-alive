"""Reading: the planner, the learned map, a device that goes quiet, short answers, the fields."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from conftest import HOUSE, run, site
from sungrow_sh_t import fields as F, hub as H, planner as P
from sungrow_sh_t.scheduler import OwnTransport, Scheduler


def house(base: int = 502) -> list[F.Device]:
    return [F.device(k, n, base + o, u) for k, n, o, u in HOUSE]


def test_every_field_is_there():
    counts = {kind: len(F.fields_for(kind)) for kind in F.KIND_NAMES}
    assert sum(counts[d.kind] for d in house()) == 380


def test_not_available_is_no_value():
    assert F.decode_reg(F.Reg("input", 0, "u16"), [0xFFFF]) is None
    assert F.decode_reg(F.Reg("input", 0, "s32"), [0xFFFF, 0x7FFF]) is None
    assert F.decode_reg(F.Reg("input", 0, "s16"), [0xFFF6]) == -10


def test_without_a_learned_map_nothing_is_merged_across_unknown_registers():
    h = H.Hub("x", house(), transport=object())
    proven = P.plan(h._reads, P.EVERYTHING)
    assert len(h.blocks) > len(proven)  # conservative until the survey
    for b in h.blocks:
        covered = set()
        for r in b.reads:
            covered |= set(range(r.address, r.end))
        assert covered == set(range(b.address, b.end)), b  # no gap bridged


def test_the_survey_learns_and_merges():
    async def go():
        async with site() as base:
            h = H.Hub("127.0.0.1", house(base), transport=OwnTransport("127.0.0.1", 1.0))
            task = asyncio.create_task(h.scheduler.run())
            before = len(h.blocks)
            assert h.survey_todo()
            done = await h.survey(pause=0)
            task.cancel()
            h.scheduler.close()
            return before, len(h.blocks), done, h
    before, after, done, h = run(go())
    assert done and h.readable and not h.survey_todo()
    assert after < before


def test_a_device_that_stops_answering_does_not_hold_the_bus(tmp_path):
    ctl = tmp_path / "ctl.json"

    async def go():
        async with site(control=ctl) as base:
            ctl.write_text(json.dumps({"timeout": [f"{base + 7}/4"]}))  # tower 4 goes quiet
            s_reads = []
            devs = house(base)
            h = H.Hub("127.0.0.1", devs, transport=OwnTransport("127.0.0.1", 0.5))
            orig = h.scheduler.on_data

            def on_data(b, regs, at):
                if (b.port, b.unit) == (base, 1) and b.interval <= 2:
                    s_reads.append(time.monotonic())
                orig(b, regs, at)

            h.scheduler.on_data = on_data
            task = asyncio.create_task(h.scheduler.run())
            await asyncio.sleep(20)
            timeouts = h.scheduler.stats.timeouts
            ctl.write_text("{}")  # and comes back
            t0 = time.monotonic()
            while h.scheduler._silent.get((base + 7, 4)) and time.monotonic() - t0 < 75:
                await asyncio.sleep(0.5)
            back = time.monotonic() - t0
            task.cancel()
            h.scheduler.close()
            gaps = [b - a for a, b in zip(s_reads, s_reads[1:]) if a > s_reads[0] + 8]
            return timeouts, max(gaps), back
    timeouts, worst, back = run(go())
    assert timeouts <= 4  # not one per block every 5 s
    assert worst < 3.0  # the fast lane keeps its pace
    assert back < 65  # and the tower is asked again within a minute


def test_a_short_answer_is_a_lost_answer():
    async def go():
        async def handle(reader, writer):
            head = await reader.readexactly(7)
            await reader.readexactly(int.from_bytes(head[4:6], "big") - 1)
            body = bytes([4, 4, 0, 1])  # claims 4 bytes, sends 2
            writer.write(head[:4] + (len(body) + 1).to_bytes(2, "big") + head[6:7] + body)
            await writer.drain()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        t = OwnTransport("127.0.0.1", 1.0)
        try:
            with pytest.raises(ConnectionError):
                await t.read(port, 1, "input", 0, 2)
        finally:
            t.close()
            server.close()
    run(go())


def test_a_new_plan_reads_every_block_again():
    s = Scheduler("x", [], lambda *a: None, transport=object())
    blocks = P.plan([P.Read("a", 502, 1, "input", 10, 2, 5)], set())
    s.set_blocks(blocks)
    assert len(s._heap) == 1

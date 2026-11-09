"""Discovery: any site comes out right, and this house comes out exactly as before."""

from __future__ import annotations

import json

from conftest import HOUSE, REGMAP, run, site
from sungrow_sh_t import fields as F, legacy as L
from sungrow_sh_t.discovery import discover, keep_keys, merge, open_ports
from sungrow_sh_t.scheduler import OwnTransport


async def _find(layout=None, ports=8):
    async with site(layout) as base:
        t = OwnTransport("127.0.0.1", 1.0)
        try:
            return base, await discover(t.read, await open_ports("127.0.0.1", range(base, base + ports)))
        finally:
            t.close()


def test_this_house_comes_out_as_the_fixed_layout_did():
    base, r = run(_find())
    got = {(d.key, d.port - base, d.unit) for d in r.devices}
    want = {(F.device(k, n, o, u).key, o, u) for k, n, o, u in HOUSE}
    assert got == want
    assert r.complete and r.expected == 7
    # each tower remembers the inverter whose battery stack it is part of (9 Nov 2026)
    assert {d.key: d.inverter for d in r.devices if d.kind == "tower"} == {
        "tower_1": "inverter_1", "tower_2": "inverter_1", "tower_3": "inverter_2", "tower_4": "inverter_2"}


def test_everything_behind_one_port():
    base, r = run(_find("one_port"))
    assert {d.port for d in r.devices} == {base}
    assert sorted(d.key for d in r.devices) == sorted(F.device(k, n, 0, 0).key for k, n, _o, _u in HOUSE)


def test_a_small_site_one_inverter_two_towers():
    _base, r = run(_find("one_inverter_two_towers"))
    assert sorted(d.key for d in r.devices) == ["inverter_1", "logger", "meter", "tower_1", "tower_2"]


def test_towers_go_with_the_inverter_whose_battery_they_share():
    """Scrambled ports and addresses, no meter: the SBR256 towers sit on the SH15T, found first here."""
    _base, r = run(_find("scrambled_no_meter"))
    by = {d.key: d for d in r.devices}
    assert by["inverter_1"].model == "SH15T"
    assert by["tower_1"].model == "SBR256"
    assert "meter" not in by


def test_nothing_there_finds_nothing():
    async def go():
        async with site() as base:
            pass  # the site is gone again: its ports are closed
        t = OwnTransport("127.0.0.1", 0.5)
        try:
            return await discover(t.read, await open_ports("127.0.0.1", range(base, base + 8)))
        finally:
            t.close()

    assert run(go()).devices == []


def test_a_new_search_keeps_known_devices_names():
    old = [F.device(k, n, 502 + o, u, serial=f"S{u}") for k, n, o, u in HOUSE]
    # tower 2 moved port; a fifth tower appeared
    found = [F.Device(d.key, d.kind, d.port + (1 if d.key == "tower_2" else 0), d.unit, d.name, serial=d.serial) for d in old]
    found.append(F.device("tower", 9, 520, 9, serial="NEW"))
    out = {d.serial: d for d in keep_keys(old, found)}
    assert out["S7"].key == "tower_2" and out["S7"].port == old[6].port + 1
    assert out["NEW"].key == "tower_5"


def test_the_yaml_move_takes_its_devices_from_the_yaml():
    """The register map is this house's Modbus YAML: hubs, entities, addresses, names."""
    conf = [{"name": h["hub"], "port": h["port"], "host": h["host"], "sensors": h["entities"]}
            for h in json.loads(REGMAP.read_text())["hubs"]]
    got = {(d.key, d.port, d.unit) for d in L.devices_from_yaml(conf)}
    assert got == {(F.device(k, n, o, u).key, 502 + o, u) for k, n, o, u in HOUSE}


def test_a_device_that_misses_one_question_is_asked_again():
    """The first search of the real Logger (9 Nov 2026) missed the meter, which answered every later
    question: while short of the Logger's own count, an address that gave nothing is asked once more."""

    async def go():
        async with site() as base:
            t = OwnTransport("127.0.0.1", 1.0)
            missed = []

            async def read(port, unit, space, address, count):
                if (unit, space, address) == (5, "holding", 4358) and not missed:
                    missed.append(port)
                    raise TimeoutError("busy with another client")
                return await t.read(port, unit, space, address, count)

            try:
                return missed, await discover(read, await open_ports("127.0.0.1", range(base, base + 8)))
            finally:
                t.close()

    missed, r = run(go())
    assert missed, "the meter's question was never asked"
    assert "meter" in {d.key for d in r.devices}
    assert r.complete and r.expected == 7


def test_a_search_over_the_yaml_moves_devices_keeps_every_key():
    """The YAML move records no serial numbers (9 Nov 2026, the first install's entry): a search afterwards matches each
    device by its address on the Logger's bus, so nothing is renumbered and no entity id changes."""
    old = [F.device(k, n, 502 + o, u, model="DTSU666-20" if k == "meter" else None) for k, n, o, u in HOUSE]  # no serials
    home = lambda k, u: ("inverter_1" if u in (6, 7) else "inverter_2") if k == "tower" else None  # noqa: E731
    found = [F.device(k, n, 502, u, serial=f"S{u}", model="DTSU666" if k == "meter" else "M", inverter=home(k, u))
             for k, n, _o, u in HOUSE]  # all behind one port
    found_by_unit = {d.unit: d for d in found}
    devices, new, missing = merge(old, found)
    by = {d.key: d for d in devices}
    assert sorted(by) == sorted(d.key for d in old) and not new and not missing
    assert all(by[d.key].serial == found_by_unit[d.unit].serial for d in old)
    assert by["meter"].model == "DTSU666-20" and by["inverter_1"].model == "M"  # the more exact model is kept
    assert {k: d.inverter for k, d in by.items() if d.kind == "tower"} == {
        "tower_1": "inverter_1", "tower_2": "inverter_1", "tower_3": "inverter_2", "tower_4": "inverter_2"}


def test_a_device_not_found_again_is_kept():
    """A device that misses a search (busy, switched off) keeps its place: its entities are not orphaned."""
    old = [F.device(k, n, 502 + o, u, serial=f"S{u}") for k, n, o, u in HOUSE]
    found = [d for d in old if d.key != "tower_4"]
    devices, new, missing = merge(old, found)
    assert "tower_4" in {d.key for d in devices} and missing == ["tower_4"] and not new


def test_a_tower_keeps_its_inverter_through_a_renumbering():
    """A found tower names a found inverter; when that inverter keeps an older key, the tower follows it."""
    old = [F.device("inverter", 1, 502, 2, serial="B"), F.device("inverter", 2, 503, 1, serial="A")]
    found = [F.device("inverter", 1, 502, 1, serial="A"), F.device("inverter", 2, 503, 2, serial="B"),
             F.device("tower", 1, 504, 3, serial="T", inverter="inverter_1")]
    devices, new, _missing = merge(old, found)
    by = {d.key: d for d in devices}
    assert by["inverter_2"].serial == "A" and by["tower_1"].inverter == "inverter_2" and new == ["tower_1"]


def test_a_search_again_asks_the_known_addresses_first_and_stops_at_the_count():
    """9 Nov 2026, the first install: a search again on a Logger busy with this integration's own polling ran out of
    time before reaching the meter. Asking the addresses found before first, the search ends at the
    Logger's count, and a known device that is busy once is asked again at once."""

    async def go():
        async with site() as base:
            t = OwnTransport("127.0.0.1", 1.0)
            asked: list[int] = []
            busy = []

            async def read(port, unit, space, address, count):
                asked.append(unit)
                if (unit, space, address) == (5, "holding", 4358) and not busy:
                    busy.append(port)
                    raise TimeoutError("busy with another client")
                return await t.read(port, unit, space, address, count)

            known = [(base + o, u) for _k, _n, o, u in HOUSE]
            try:
                ports = await open_ports("127.0.0.1", range(base, base + 8))
                return asked, await discover(read, ports, known=known)
            finally:
                t.close()

    asked, r = run(go())
    assert r.complete and "meter" in {d.key for d in r.devices}
    # nothing beyond the known addresses was asked: no walk of every other address
    assert set(asked) <= {u for _k, _n, _o, u in HOUSE}


def test_a_bigger_site_three_inverters_six_towers():
    """Three SH inverters and six battery towers behind one Logger (a tester's site, 9 Nov 2026): all are
    found, numbered in order, each with its own serial, and the search ends at the Logger's count."""
    _base, r = run(_find("three_inverters_six_towers", ports=1))
    keys = sorted(d.key for d in r.devices)
    assert keys == ["inverter_1", "inverter_2", "inverter_3", "logger", "meter",
                    "tower_1", "tower_2", "tower_3", "tower_4", "tower_5", "tower_6"]
    assert r.complete and r.expected == 10  # the meter counts too
    serials = [d.serial for d in r.devices if d.kind in ("inverter", "tower")]
    assert len(set(serials)) == len(serials) == 9

"""The dashboard: this house's is the approved one, unchanged; another site gets exactly its own entities."""

from __future__ import annotations

import json
import re

from conftest import PKG, ROOT, load
from sungrow_sh_t import fields as F

layout = load(PKG / "layout.py", "sungrow_layout")
SNAPSHOT = ROOT / "tests" / "data" / "app_house.json"
IDS = re.compile(r'"((?:sensor|binary_sensor|number|select)\.[a-z0-9_]+)"')


def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def named(devices) -> set[str]:
    return {f"{f.control['kind'] if f.control else f.platform}.{slug(d.name + ' ' + f.name)}" for d in devices for f in F.fields_for(d.kind)}


def test_this_house_dashboard_is_the_approved_one():
    """Any change to the approved layout shows up here; update the snapshot only on purpose."""
    got = layout.build([1, 2], [1, 2, 3, 4])
    assert json.loads(json.dumps(got)) == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_a_small_site_references_only_what_it_has():
    small = [F.device("inverter", 1, 502, 1), F.device("tower", 1, 502, 3), F.device("tower", 2, 502, 4), F.device("logger", 0, 502, 247)]
    have = named(small)
    cfg = layout.prune(layout.build([1], [1, 2])["views"][0]["cards"][0], have)
    used = set(IDS.findall(json.dumps(cfg)))
    assert used and used <= have
    pages = {p["id"]: p for p in cfg["pages"]}
    grid_cards = [c["type"] for c in pages["grid"]["cards"]]
    assert "custom:sungrow-grid-card" not in grid_cards  # no meter: its designed card goes
    battery = next(c for c in pages["battery"]["cards"] if c["type"] == "custom:sungrow-battery-card")
    assert battery["towers"] == [1, 2]


def test_every_entity_of_this_house_has_a_place():
    devices = [F.device(k, n, 502 + o, u) for k, n, o, u in __import__("conftest").HOUSE]
    used = set(IDS.findall(json.dumps(layout.build([1, 2], [1, 2, 3, 4]))))
    left = named(devices) - used
    # the towers' temperature register reads a fixed value through the Logger and is left out on purpose
    assert left == {f"sensor.sungrow_battery_tower_{t}_temperature_register_fixed" for t in (1, 2, 3, 4)}


def test_each_tower_shows_its_stacks_temperature_from_its_inverter():
    """9 Nov 2026: a tower's own temperature register holds a fixed 14 °C through a Logger1000, so the towers'
    table shows the stack's temperature its inverter measures, saying so under each value; a tower whose
    stack is not known shows none rather than a guess. The register stays, hidden and disabled."""
    cfg = layout.build([1, 2], [1, 2, 3], {1: (1, "SH25T"), 2: (1, "SH25T"), 3: (2, "SH15T")})
    battery = next(p for p in cfg["views"][0]["cards"][0]["pages"] if p["id"] == "battery")
    (temp,) = [r for g in _groups(battery) for r in g.get("rows", []) if r.get("subs")]
    assert temp["entities"] == [
        "sensor.sungrow_inverter_1_battery_temperature",
        "sensor.sungrow_inverter_1_battery_temperature",
        "sensor.sungrow_inverter_2_battery_temperature",
    ]
    assert temp["subs"] == ["stack, from SH25T", "stack, from SH25T", "stack, from SH15T"]

    partly = layout.build([1, 2], [1, 2], {1: (1, "SH25T")})
    bat = next(p for p in partly["views"][0]["cards"][0]["pages"] if p["id"] == "battery")
    (temp,) = [r for g in _groups(bat) for r in g.get("rows", []) if r.get("subs")]
    assert temp["entities"] == ["sensor.sungrow_inverter_1_battery_temperature", None]

    reg = next(f for f in F.fields_for("tower") if f.key == "temperature")
    assert (reg.category, reg.enabled) == ("diagnostic", False)


def _groups(node):
    """Every table group in a page, however deep."""
    if isinstance(node, dict):
        if "rows" in node and "title" in node:
            yield node
        for v in node.values():
            yield from _groups(v)
    elif isinstance(node, list):
        for v in node:
            yield from _groups(v)

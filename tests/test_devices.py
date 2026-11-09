"""Device pages: make, model, serial number, and where each device is connected; the battery tower and
forget choices in Configure."""

from __future__ import annotations

from dataclasses import replace

from conftest import HOUSE
from sungrow_sh_t import devices as D, fields as F

E = "entry"


def _house(**towers: str) -> list[F.Device]:
    return [replace(d, inverter=towers.get(d.key))
            for d in (F.device(k, n, 502 + o, u, serial=f"S{u}", model="M") for k, n, o, u in HOUSE)]


def test_towers_sit_under_their_inverter_and_the_rest_under_the_logger():
    devices = _house(tower_1="inverter_1", tower_2="inverter_1", tower_3="inverter_2", tower_4="inverter_2")
    via = {d.key: D.info(E, d, devices).get("via_device") for d in devices}
    assert via == {
        "logger": None,
        "inverter_1": (D.DOMAIN, "entry_logger"), "inverter_2": (D.DOMAIN, "entry_logger"), "meter": (D.DOMAIN, "entry_logger"),
        "tower_1": (D.DOMAIN, "entry_inverter_1"), "tower_2": (D.DOMAIN, "entry_inverter_1"),
        "tower_3": (D.DOMAIN, "entry_inverter_2"), "tower_4": (D.DOMAIN, "entry_inverter_2"),
    }


def test_a_tower_whose_inverter_is_not_known_sits_under_the_logger():
    devices = _house()
    assert D.info(E, next(d for d in devices if d.key == "tower_1"), devices)["via_device"] == (D.DOMAIN, "entry_logger")


def test_a_site_without_a_logger_device_has_no_parents():
    devices = [d for d in _house() if d.kind != "logger"]
    assert all("via_device" not in D.info(E, d, devices) for d in devices if d.kind != "tower")


def test_the_page_shows_serial_and_model_and_keeps_the_ids_entities_use():
    """The identifier is the one every entity already has (entry_id + key): no device is duplicated."""
    devices = _house()
    inv = D.info(E, devices[0], devices)
    assert inv["identifiers"] == {(D.DOMAIN, "entry_inverter_1")}
    assert (inv["manufacturer"], inv["model"], inv["serial_number"]) == ("Sungrow", "M", "S1")
    # a move from YAML records neither: nothing is made up
    bare = F.device("tower", 1, 506, 6)
    assert "serial_number" not in D.info(E, bare, [bare]) and "model" not in D.info(E, bare, [bare])
    meter = F.device("meter", 0, 504, 5)
    assert D.info(E, meter, [meter])["manufacturer"] == "CHINT"


def test_parents_are_registered_first():
    order = [d.kind for d in D.in_order(_house())]
    assert order.index("logger") < min(i for i, k in enumerate(order) if k in ("inverter", "meter"))
    assert max(i for i, k in enumerate(order) if k in ("inverter", "meter")) < min(i for i, k in enumerate(order) if k == "tower")


def test_choosing_each_towers_inverter():
    raw = [d.as_dict() for d in _house(tower_1="inverter_2")]
    out = {d["key"]: d.get("inverter") for d in D.set_towers(raw, {"tower_1": "inverter_1", "tower_2": D.NO_INVERTER, "tower_3": "inverter_2"})}
    assert (out["tower_1"], out["tower_2"], out["tower_3"], out["tower_4"]) == ("inverter_1", None, "inverter_2", None)
    assert [c["value"] for c in D.tower_choices(_house())] == ["inverter_1", "inverter_2", D.NO_INVERTER]


def test_forgetting_an_inverter_leaves_its_towers_unplaced():
    raw = [d.as_dict() for d in _house(tower_3="inverter_2", tower_4="inverter_2", tower_1="inverter_1")]
    out = {d["key"]: d for d in D.forget(raw, ["inverter_2"])}
    assert "inverter_2" not in out
    assert "inverter" not in out["tower_3"] and out["tower_1"]["inverter"] == "inverter_1"

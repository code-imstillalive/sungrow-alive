"""The unit standard (docs/design.md): one unit and one display precision per
quantity, everywhere.

Each quantity maps a device's native unit to the standard one. Values are
converted exactly (W -> kW is /1000, nothing rounded); the shown decimals are
Home Assistant's `suggested_display_precision`, so the stored value keeps the
device's full resolution.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quantity:
    unit: str | None
    precision: int
    device_class: str | None
    state_class: str | None
    native: str | None  # the unit the registers count in
    factor: float = 1.0  # native -> standard


Q: dict[str, Quantity] = {
    "power": Quantity("kW", 3, "power", "measurement", "W", 0.001),
    "reactive_power": Quantity("kvar", 3, "reactive_power", "measurement", "var", 0.001),
    "apparent_power": Quantity("kVA", 3, "apparent_power", "measurement", "VA", 0.001),
    "energy": Quantity("kWh", 1, "energy", "total_increasing", "kWh"),
    "energy_storage": Quantity("kWh", 1, "energy_storage", "measurement", "kWh"),
    "voltage": Quantity("V", 1, "voltage", "measurement", "V"),
    "cell_delta": Quantity("mV", 0, "voltage", "measurement", "mV"),
    "current": Quantity("A", 1, "current", "measurement", "A"),
    "frequency": Quantity("Hz", 2, "frequency", "measurement", "Hz"),
    "temperature": Quantity("°C", 1, "temperature", "measurement", "°C"),
    "battery": Quantity("%", 1, "battery", "measurement", "%"),
    "percent": Quantity("%", 1, None, "measurement", "%"),
    "power_factor": Quantity(None, 3, "power_factor", "measurement", None),
    "duration": Quantity("s", 0, "duration", "measurement", "s"),
    "count": Quantity(None, 0, None, "measurement", None),
    "text": Quantity(None, 0, None, None, None),
    "enum": Quantity(None, 0, "enum", None, None),
}

#: Units other Modbus setups publish, and their standard one (`W` -> kW and so on).
TO_STANDARD = {"W": ("kW", 0.001), "var": ("kvar", 0.001), "VA": ("kVA", 0.001)}

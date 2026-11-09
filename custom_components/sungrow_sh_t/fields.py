"""Every value the integration publishes, defined once, straight from the registers.

This replaces both layers of the YAML: the 154 raw Modbus reads (often packed
blocks published as comma-joined strings) and the 387 Jinja templates that
unpicked them. A field names its registers, how they are typed, and how the
value is worked out; the planner turns the registers into requests.

Addresses are the wire addresses (protocol register number minus 1), the same
numbers the YAML uses. Word order: Sungrow sends 32-bit values low word first
(`u32`/`s32`); the CHINT meter and the Logger's 64-bit counters high word
first (`u32be`/`s32be`/`u64be`/`s64be`).

Nothing here names one install: which entity of an install's own setup a field corresponds
to is that install's business, never kept here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TIERS = {"fast": 5, "normal": 10, "slow": 30, "setting": 60, "static": 3600}

_WIDTH = {"u16": 1, "s16": 1, "u32": 2, "s32": 2, "u32be": 2, "s32be": 2, "u64be": 4, "s64be": 4}


@dataclass(frozen=True)
class Reg:
    space: str  # "input" or "holding"
    address: int
    type: str  # see _WIDTH, or "str<N>" for N registers of text

    @property
    def count(self) -> int:
        return int(self.type[3:]) if self.type.startswith("str") else _WIDTH[self.type]


@dataclass(frozen=True)
class Field:
    key: str
    name: str
    regs: tuple[Reg, ...]
    quantity: str
    tier: str = "normal"
    scale: float = 1.0  # single-register fields: native = raw * scale
    calc: Callable[..., Any] | None = None  # derived: calc(*decoded regs)
    platform: str = "sensor"
    options: dict[int, str] | None = None  # enum: raw code -> text
    category: str | None = None  # None, "diagnostic" or "config"
    delay_on: int = 0  # binary sensors: seconds a True must last
    attrs: dict[str, Any] = field(default_factory=dict)
    #: a setting the user can change: {"kind": "number"|"select", "min", "max",
    #: "step" in native units, or "min_key"/"max_key": another field of the same
    #: device that holds the bound (the inverter's own reported range)}
    control: dict[str, Any] | None = None
    #: False: the entity starts disabled (a register that is not a reading on every site)
    enabled: bool = True


def encode_native(f: Field, native: float | int) -> list[int]:
    """The words to write for a native value (or an option's code) of a one-register-set field."""
    reg = f.regs[0]
    raw = int(round(native / f.scale)) if f.options is None else int(native)
    if reg.type in ("u16", "s16"):
        return [raw & 0xFFFF]
    if reg.type in ("u32", "s32"):  # low word first
        raw &= 0xFFFFFFFF
        return [raw & 0xFFFF, raw >> 16]
    raise ValueError(f"{f.key}: cannot write {reg.type}")


#: Protocol section 1.2, item 5: an unavailable register answers with these.
#: They are "no value", never a reading (read naively, 0x7FFFFFFF export power
#: would show as 2,147,483,647 W).
NOT_AVAILABLE = {
    "u16": 0xFFFF, "s16": 0x7FFF, "u32": 0xFFFFFFFF, "s32": 0x7FFFFFFF,
    "u32be": 0xFFFFFFFF, "s32be": 0x7FFFFFFF,
}


def decode_reg(reg: Reg, words: list[int]) -> Any:
    """Turn a register's words into a number or text; None for "not available"."""
    t = reg.type
    if t.startswith("str"):
        raw = b"".join(w.to_bytes(2, "big") for w in words)
        return raw.split(b"\x00", 1)[0].decode(errors="replace").strip()
    if t in ("u16", "s16") and words[0] == NOT_AVAILABLE[t]:
        return None
    if t == "u16":
        return words[0]
    if t == "s16":
        return words[0] - 0x10000 if words[0] & 0x8000 else words[0]
    if t in ("u32", "s32"):
        v = words[1] << 16 | words[0]
    elif t in ("u32be", "s32be"):
        v = words[0] << 16 | words[1]
    else:  # 64-bit, high word first
        v = words[0] << 48 | words[1] << 32 | words[2] << 16 | words[3]
    if NOT_AVAILABLE.get(t) == v:
        return None
    if t[0] == "s":
        bits = 64 if "64" in t else 32
        if v >> (bits - 1):
            v -= 1 << bits
    return v


def value(f: Field, decoded: list[Any]) -> Any:
    """A field's value in its native unit, or None when it cannot be known."""
    if any(d is None for d in decoded):
        return None
    if f.calc is not None:
        return f.calc(*decoded)
    v = decoded[0]
    if f.options is not None:
        return f.options.get(v, f"unknown ({v:#06x})")
    if isinstance(v, str):
        return v
    return v * f.scale if f.scale != 1 else v


def _bit(n: int) -> Callable[[int], bool]:
    return lambda flow: bool(flow >> n & 1)


I, H = "input", "holding"

AA55 = {0xAA: "Enabled", 0x55: "Disabled"}
DEVICE_TYPE = {
    0x0E20: "SH5T", 0x0E21: "SH6T", 0x0E22: "SH8T", 0x0E23: "SH10T",
    0x0E24: "SH12T", 0x0E25: "SH15T", 0x0E26: "SH20T", 0x0E28: "SH25T",
}
RUNNING_STATE = {
    0x0000: "Running", 0x0040: "Running", 0x0410: "Off-grid charge", 0x0200: "Update failed",
    0x0400: "Maintain mode", 0x0800: "Forced mode", 0x1000: "Off-grid mode",
    0x1111: "Un-initialized", 0x0010: "Initial standby", 0x12000: "Initial standby",
    0x1300: "Shutdown", 0x0002: "Shutdown", 0x1400: "Standby", 0x0008: "Standby",
    0x1500: "Emergency stop", 0x0004: "Emergency stop", 0x1600: "Startup", 0x0020: "Startup",
    0x1700: "AFCI self test shutdown", 0x1800: "Intelligent station building",
    0x1900: "Safe mode", 0x2000: "Open loop", 0x2501: "Restarting",
    0x4000: "External EMS mode", 0x4001: "Emergency battery charging", 0x5500: "Fault",
    0x0100: "Fault", 0x8000: "Stop", 0x0001: "Stop", 0x8100: "De-rating running",
    0x0080: "De-rating running", 0x8200: "Dispatch run", 0x9100: "Warn running",
}
EMS_MODE = {0: "Self-consumption", 2: "Forced mode", 3: "External EMS", 4: "VPP"}
FORCED_CMD = {0xCC: "Stop", 0xAA: "Forced charge", 0xBB: "Forced discharge"}


def inverter() -> list[Field]:
    """One SH-T hybrid inverter."""


    fields = [
        # identity: read at start, then hourly
        Field("serial", "Serial number", (Reg(I, 4989, "str10"),), "text", "static", category="diagnostic"),
        Field("device_type", "Model", (Reg(I, 4999, "u16"),), "enum", "static", options=DEVICE_TYPE, category="diagnostic"),
        Field("rated_power", "Rated output power", (Reg(I, 5000, "u16"),), "power", "static", scale=100, category="diagnostic"),
        # energy counters
        Field("daily_output_energy", "Daily output energy", (Reg(I, 5002, "u16"),), "energy", scale=0.1),
        Field("total_output_energy", "Total output energy", (Reg(I, 5003, "u32"),), "energy", scale=0.1),
        Field("temperature", "Inverter temperature", (Reg(I, 5007, "s16"),), "temperature", scale=0.1),
        # PV
        *[
            f
            for m in (1, 2, 3)
            for f in (
                Field(f"mppt{m}_voltage", f"MPPT{m} voltage", (Reg(I, 5008 + 2 * m, "u16"),), "voltage", "fast", scale=0.1),
                Field(f"mppt{m}_current", f"MPPT{m} current", (Reg(I, 5009 + 2 * m, "u16"),), "current", "fast", scale=0.1),
                Field(
                    f"mppt{m}_power", f"MPPT{m} power",
                    (Reg(I, 5008 + 2 * m, "u16"), Reg(I, 5009 + 2 * m, "u16")), "power", "fast",
                    calc=lambda v, i: v * i / 100,
                ),
            )
        ],
        Field("pv_power", "PV power", (Reg(I, 5016, "u32"),), "power", "fast"),
        *[
            f
            for k in range(1, 6)
            for f in (
                Field(f"string{k}_voltage", f"String {k} voltage", (Reg(I, 5250 + 2 * k, "u16"),), "voltage", scale=0.1),
                Field(f"string{k}_current", f"String {k} current", (Reg(I, 5251 + 2 * k, "u16"),), "current", scale=0.01),
                Field(
                    f"string{k}_power", f"String {k} power",
                    (Reg(I, 5250 + 2 * k, "u16"), Reg(I, 5251 + 2 * k, "u16")), "power",
                    calc=lambda v, i: v * i / 1000,
                ),
            )
        ],
        # grid side of the inverter
        *[
            Field(f"phase_{ph}_voltage", f"Phase {ph.upper()} voltage", (Reg(I, 5018 + j, "u16"),), "voltage", scale=0.1)
            for j, ph in enumerate("abc")
        ],
        Field("reactive_power", "Reactive power", (Reg(I, 5032, "s32"),), "reactive_power"),
        Field("power_factor", "Power factor", (Reg(I, 5034, "s16"),), "power_factor", scale=0.001),
        Field("grid_frequency", "Grid frequency", (Reg(I, 5241, "u16"),), "frequency", scale=0.01),
        *[
            Field(f"phase_{ph}_current", f"Phase {ph.upper()} current", (Reg(I, 13030 + j, "s16"),), "current", scale=0.1)
            for j, ph in enumerate("abc")
        ],
        *[
            Field(
                f"phase_{ph}_power", f"Phase {ph.upper()} power",
                (Reg(I, 5018 + j, "u16"), Reg(I, 13030 + j, "s16")), "power",
                calc=lambda v, i: v * i / 100,
            )
            for j, ph in enumerate("abc")
        ],
        Field("active_power", "Active power", (Reg(I, 13033, "s32"),), "power", "fast"),
        # site, as the inverter's own meter sees it
        Field("load_power", "Load power", (Reg(I, 13007, "s32"),), "power", "fast"),
        Field("export_power", "Export power", (Reg(I, 13009, "s32"),), "power", "fast", calc=lambda v: max(v, 0)),
        Field("import_power", "Import power", (Reg(I, 13009, "s32"),), "power", "fast", calc=lambda v: max(-v, 0)),
        Field("meter_power", "Meter active power", (Reg(I, 5600, "s32"),), "power", "fast"),
        *[
            Field(f"meter_phase_{ph}_power", f"Meter phase {ph.upper()} power", (Reg(I, 5602 + 2 * j, "s32"),), "power")
            for j, ph in enumerate("abc")
        ],
        Field("meter_frequency", "Meter frequency", (Reg(I, 5736, "u16"),), "frequency", scale=0.01),
        *[
            Field(f"meter_phase_{ph}_voltage", f"Meter phase {ph.upper()} voltage", (Reg(I, 5740 + j, "u16"),), "voltage", scale=0.1)
            for j, ph in enumerate("abc")
        ],
        *[
            Field(f"meter_phase_{ph}_current", f"Meter phase {ph.upper()} current", (Reg(I, 5743 + j, "u16"),), "current", scale=0.01)
            for j, ph in enumerate("abc")
        ],
        # whole-home backup
        *[
            f
            for j, ph in enumerate("abc")
            for f in (
                Field(f"backup_{ph}_current", f"Backup phase {ph.upper()} current", (Reg(I, 5719 + j, "s16"),), "current", scale=0.1),
                Field(f"backup_{ph}_power", f"Backup phase {ph.upper()} power", (Reg(I, 5722 + j, "s16"),), "power"),
                Field(f"backup_{ph}_voltage", f"Backup phase {ph.upper()} voltage", (Reg(I, 5730 + j, "u16"),), "voltage", scale=0.1),
            )
        ],
        Field("backup_power", "Backup power", (Reg(I, 5725, "s32"),), "power"),
        Field("backup_frequency", "Backup frequency", (Reg(I, 5733, "u16"),), "frequency", scale=0.01),
        # battery
        Field("bdc_rated_power", "Battery converter rated power", (Reg(I, 5627, "u16"),), "power", "slow", scale=100, category="diagnostic"),
        Field("bms_max_charge_current", "BMS max charge current", (Reg(I, 5634, "u16"),), "current", "slow", category="diagnostic"),
        Field("bms_max_discharge_current", "BMS max discharge current", (Reg(I, 5635, "u16"),), "current", "slow", category="diagnostic"),
        Field("battery_capacity", "Battery capacity", (Reg(I, 5638, "u16"),), "energy_storage", "slow", scale=0.01),
        Field("battery_voltage", "Battery voltage", (Reg(I, 13019, "u16"),), "voltage", scale=0.1),
        Field("battery_current", "Battery current", (Reg(I, 13020, "s16"),), "current", scale=0.1),
        Field("battery_power", "Battery power", (Reg(I, 5213, "s32"),), "power", "fast",
              attrs={"sign": "positive = discharging"}),
        Field("battery_charging_power", "Battery charging power", (Reg(I, 5213, "s32"),), "power", "fast", calc=lambda p_: max(-p_, 0)),
        Field("battery_discharging_power", "Battery discharging power", (Reg(I, 5213, "s32"),), "power", "fast", calc=lambda p_: max(p_, 0)),
        Field("battery_level", "Battery level", (Reg(I, 13022, "u16"),), "battery", scale=0.1),
        Field("battery_soh", "Battery state of health", (Reg(I, 13023, "u16"),), "percent", "slow", scale=0.1),
        Field("battery_temperature", "Battery temperature", (Reg(I, 13024, "s16"),), "temperature", scale=0.1),
        # daily and total energy
        Field("daily_pv_energy", "Daily PV generation", (Reg(I, 13001, "u16"),), "energy", scale=0.1),
        Field("total_pv_energy", "Total PV generation", (Reg(I, 13002, "u32"),), "energy", scale=0.1),
        Field("daily_battery_discharge", "Daily battery discharge", (Reg(I, 13025, "u16"),), "energy", scale=0.1),
        Field("total_battery_discharge", "Total battery discharge", (Reg(I, 13026, "u32"),), "energy", scale=0.1),
        Field("daily_import_energy", "Daily import energy", (Reg(I, 13035, "u16"),), "energy", scale=0.1),
        Field("total_import_energy", "Total import energy", (Reg(I, 13036, "u32"),), "energy", scale=0.1),
        Field("daily_battery_charge", "Daily battery charge", (Reg(I, 13039, "u16"),), "energy", scale=0.1),
        Field("total_battery_charge", "Total battery charge", (Reg(I, 13040, "u32"),), "energy", scale=0.1),
        Field("daily_export_energy", "Daily export energy", (Reg(I, 13044, "u16"),), "energy", scale=0.1),
        Field("total_export_energy", "Total export energy", (Reg(I, 13045, "u32"),), "energy", scale=0.1),
        Field(
            "daily_consumed_energy", "Daily consumed energy",
            (Reg(I, 5002, "u16"), Reg(I, 13044, "u16"), Reg(I, 13035, "u16")), "energy",
            calc=lambda out, exp, imp: (out - exp + imp) / 10,
        ),
        Field(
            "total_consumed_energy", "Total consumed energy",
            (Reg(I, 5003, "u32"), Reg(I, 13045, "u32"), Reg(I, 13036, "u32")), "energy",
            calc=lambda out, exp, imp: (out - exp + imp) / 10,
        ),
        # state
        Field("running_state", "Running state", (Reg(I, 12999, "u16"),), "enum", options=RUNNING_STATE),
        *[
            f
            for b, key, name, uid in (
                (0, "pv_generating", "PV generating", "pv_generating"),
                (1, "battery_charging", "Battery charging", "battery_charging"),
                (2, "battery_discharging", "Battery discharging", "battery_discharging"),
                (3, "powering_loads", "Powering loads", "power_flow_to_load"),
                (4, "exporting", "Exporting power", "exporting_power"),
                (5, "importing", "Importing power", "importing_power"),
                (7, "loads_generating", "Loads generating", "loads_generating"),
            )
            for f in (
                Field(key, name, (Reg(I, 13000, "u16"),), "count", "fast", calc=_bit(b), platform="binary_sensor"),
                Field(f"{key}_delayed", f"{name} (60 s)", (Reg(I, 13000, "u16"),), "count", "fast", calc=_bit(b), platform="binary_sensor",
                      delay_on=60),
            )
        ],
        Field("export_limit_min", "Export limit minimum", (Reg(I, 5621, "u16"),), "power", "static", scale=10, category="diagnostic"),
        Field("export_limit_max", "Export limit maximum", (Reg(I, 5622, "u16"),), "power", "static", scale=10, category="diagnostic"),
        # settings (holding registers): read every 60 s and right after a write
        Field("pv_power_limitation", "PV power limitation", (Reg(H, 13017, "u16"),), "enum", "setting",
              options={0xAA: "Limit PV", 0x55: "Allow PV"}, category="config"),
        Field("off_grid", "Backup (off-grid) option", (Reg(H, 13074, "u16"),), "enum", "setting", options=AA55, category="config"),
        Field("feed_in_limitation", "Feed-in limitation", (Reg(H, 13086, "u16"),), "enum", "setting", options=AA55, category="config"),
        Field("feed_in_ratio", "Feed-in limitation ratio", (Reg(H, 13087, "u16"),), "percent", "setting", scale=0.1, category="config"),
        Field(
            "system_mode", "System mode", (Reg(I, 12999, "u16"), Reg(H, 13049, "u16"), Reg(H, 13050, "u16")), "enum", "setting",
            calc=lambda state, ems, cmd: "Shutdown" if state in (0x1300, 0x0002) else
            "Forced charge" if ems == 2 and cmd == 0xAA else "Forced discharge" if ems == 2 and cmd == 0xBB else "Self-consumption",
            category="config",
        ),
        Field("ems_mode", "EMS mode", (Reg(H, 13049, "u16"),), "enum", "setting", options=EMS_MODE, category="config"),
        Field("forced_command", "Forced charge/discharge", (Reg(H, 13050, "u16"),), "enum", "setting", options=FORCED_CMD, category="config"),
        Field("forced_power", "Forced charge/discharge power", (Reg(H, 13051, "u16"),), "power", "setting", category="config"),
        Field("max_soc", "Max SoC", (Reg(H, 13057, "u16"),), "percent", "setting", scale=0.1, category="config"),
        Field("min_soc", "Min SoC", (Reg(H, 13058, "u16"),), "percent", "setting", scale=0.1, category="config"),
        Field("export_limit", "Export power limit", (Reg(H, 13073, "u16"),), "power", "setting", category="config"),
        Field(
            "export_limit_mode", "Export limit mode", (Reg(H, 13086, "u16"), Reg(H, 31225, "u16")), "enum", "setting",
            calc=lambda m, per: {(0xAA, 0x55): "Enabled", (0x55, 0xAA): "Enabled per phase", (0x55, 0x55): "Disabled"}.get((m, per), f"unknown ({m:#x}, {per:#x})"),
            category="config",
        ),
        Field("reserved_soc_backup", "Reserved SoC for backup", (Reg(H, 13099, "u16"),), "percent", "setting", category="config"),
        Field("power_decline_gradient", "Power decline gradient", (Reg(H, 31200, "u16"),), "percent", "setting", category="config"),
        Field("power_rising_gradient", "Power rising gradient", (Reg(H, 31201, "u16"),), "percent", "setting", category="config"),
        Field("active_power_limitation", "Active power limitation", (Reg(H, 31203, "u16"),), "enum", "setting", options=AA55, category="config"),
        Field("active_power_limit_ratio", "Active power limit ratio", (Reg(H, 31204, "u16"),), "percent", "setting", scale=0.1, category="config"),
        Field(
            "active_power_limit", "Active power limit",
            (Reg(I, 5000, "u16"), Reg(H, 31204, "u16"), Reg(H, 31203, "u16")), "power", "setting",
            calc=lambda rated, ratio, mode: rated * 100 if mode == 0x55 else rated * 100 * ratio / 1000,
            category="config",
        ),
        Field("export_limit_fallback", "Export limit fallback", (Reg(H, 31207, "u16"),), "power", "setting", scale=10, category="config"),
        Field("power_decline_gradient_fallback", "Power decline gradient fallback", (Reg(H, 31208, "u16"),), "percent", "setting", category="config"),
        Field("power_rising_gradient_fallback", "Power rising gradient fallback", (Reg(H, 31209, "u16"),), "percent", "setting", category="config"),
        Field("apl_shutdown_at_zero", "Shut down at 0% power limit", (Reg(H, 31212, "u16"),), "enum", "setting",
              options={0xAA: "On", 0x55: "Off"}, category="config"),
        Field("site_import_limit", "Site import limit", (Reg(H, 32997, "u16"),), "power", "setting", scale=10, category="config"),
        Field("max_charge_power", "Max battery charge power", (Reg(H, 33046, "u16"),), "power", "setting", scale=10, category="config"),
        Field("max_discharge_power", "Max battery discharge power", (Reg(H, 33047, "u16"),), "power", "setting", scale=10, category="config"),
        # battery figures worked out from the above
        Field(
            "battery_level_nominal", "Battery level (nominal)",
            (Reg(H, 13058, "u16"), Reg(H, 13057, "u16"), Reg(I, 13022, "u16")), "battery",
            calc=lambda lo, hi, soc: lo / 10 + (hi - lo) / 10 * soc / 1000,
        ),
        Field(
            "battery_charge", "Battery charge",
            (Reg(I, 5638, "u16"), Reg(H, 13057, "u16"), Reg(H, 13058, "u16"), Reg(I, 13022, "u16")), "energy_storage",
            calc=lambda cap, hi, lo, soc: cap / 100 * (hi - lo) / 1000 * soc / 1000,
        ),
        Field(
            "battery_charge_nominal", "Battery charge (nominal)",
            (Reg(I, 5638, "u16"), Reg(H, 13058, "u16"), Reg(H, 13057, "u16"), Reg(I, 13022, "u16")), "energy_storage",
            calc=lambda cap, lo, hi, soc: cap / 100 * (lo / 10 + (hi - lo) / 10 * soc / 1000) / 100,
        ),
        Field(
            "battery_charge_health_rated", "Battery charge (health-rated)",
            (Reg(I, 5638, "u16"), Reg(H, 13057, "u16"), Reg(H, 13058, "u16"), Reg(I, 13022, "u16"), Reg(I, 13023, "u16")), "energy_storage",
            calc=lambda cap, hi, lo, soc, soh: cap / 100 * (hi - lo) / 1000 * soc / 1000 * soh / 1000,
        ),
    ]
    return fields


# Composite controls: one setting that writes several registers, in the order a
# working installation proved: start/stop first, then the command, then EMS mode.
AA, X55 = 0xAA, 0x55
SYSTEM_MODE_WRITES = {  # option -> [(holding address, value)]: start/stop, command, EMS mode
    "Shutdown": [(12999, 0xCE), (13050, 0xCC), (13049, 0)],
    "Self-consumption": [(12999, 0xCF), (13050, 0xCC), (13049, 0)],
    "Forced charge": [(12999, 0xCF), (13050, 0xAA), (13049, 2)],
    "Forced discharge": [(12999, 0xCF), (13050, 0xBB), (13049, 2)],
}
EXPORT_MODE_WRITES = {  # option -> feed-in limitation (13086), per-phase limitation (31225)
    "Enabled": [(13086, AA), (31225, X55)],
    "Enabled per phase": [(13086, X55), (31225, AA)],
    "Disabled": [(13086, X55), (31225, X55)],
}


def _output_limit_writes(watts: float, get) -> list[tuple[int, int]]:
    """Active power limit in W -> enable (31203), shutdown-at-0 off (31212), ratio (31204, 0.1 %)."""
    rated = get("rated_power")
    if not rated:  # never guess a rating: the inverter reports its own
        raise ValueError("the inverter's rated power has not been read yet; try again in a moment")
    pct = max(0.0, min(100.0, watts / rated * 100))
    return [(31203, AA if pct < 100 else X55), (31212, X55), (31204, int(round(pct * 10)))]


INVERTER_CONTROLS: dict[str, dict[str, Any]] = {
    "system_mode": {"kind": "select", "options": list(SYSTEM_MODE_WRITES), "writes": lambda o, get: SYSTEM_MODE_WRITES[o]},
    "export_limit_mode": {"kind": "select", "options": list(EXPORT_MODE_WRITES), "writes": lambda o, get: EXPORT_MODE_WRITES[o]},
    "active_power_limit": {"kind": "number", "min": 0, "max_key": "rated_power", "step": 100, "writes": _output_limit_writes},
    "power_rising_gradient": {"kind": "number", "min": 0, "max": 1200, "step": 25},
    "power_decline_gradient": {"kind": "number", "min": 0, "max": 1200, "step": 25},
    "power_rising_gradient_fallback": {"kind": "number", "min": 0, "max": 1200, "step": 25},
    "power_decline_gradient_fallback": {"kind": "number", "min": 0, "max": 1200, "step": 25},
    "ems_mode": {"kind": "select"},
    "forced_command": {"kind": "select"},
    "forced_power": {"kind": "number", "min": 0, "max_key": "bdc_rated_power", "step": 1},
    "max_soc": {"kind": "number", "min": 50, "max": 100, "step": 0.1},
    "min_soc": {"kind": "number", "min": 0, "max": 50, "step": 0.1},
    "export_limit": {"kind": "number", "min_key": "export_limit_min", "max_key": "export_limit_max", "step": 1},
    "reserved_soc_backup": {"kind": "number", "min": 0, "max": 100, "step": 1},
    "active_power_limitation": {"kind": "select"},
    "active_power_limit_ratio": {"kind": "number", "min": 0, "max": 100, "step": 0.1},
    "export_limit_fallback": {"kind": "number", "min": 10, "max_key": "rated_power", "step": 10},
    "apl_shutdown_at_zero": {"kind": "select"},
    "site_import_limit": {"kind": "number", "min": 0, "max": 100000, "step": 10},
    "max_charge_power": {"kind": "number", "min": 0, "max_key": "bdc_rated_power", "step": 10},
    "max_discharge_power": {"kind": "number", "min": 0, "max_key": "bdc_rated_power", "step": 10},
    "pv_power_limitation": {"kind": "select"},
    "off_grid": {"kind": "select"},
    "feed_in_limitation": {"kind": "select"},
    "feed_in_ratio": {"kind": "number", "min": 0, "max": 100, "step": 0.1},
}


def _with_controls(fields: list[Field], table: dict[str, dict[str, Any]]) -> list[Field]:
    from dataclasses import replace

    out = []
    for f in fields:
        if f.key in table:
            ctl = table[f.key]
            out.append(replace(f, control=ctl, category="config") if ctl.get("writes") else replace(f, control=ctl))
        elif f.category == "config":
            out.append(replace(f, category="diagnostic"))  # a read-only setting
        else:
            out.append(f)
    return out


def meter() -> list[Field]:
    """The CHINT DTSU666-20 grid meter (unit 5): holding registers, high word first."""
    ph = "abc"
    return [
        *[Field(f"voltage_{a}{b}", f"Line voltage {a.upper()}-{b.upper()}", (Reg(H, 4352 + 2 * j, "u32be"),), "voltage", scale=0.1)
          for j, (a, b) in enumerate(("ab", "bc", "ca"))],
        *[Field(f"voltage_{x}", f"Phase {x.upper()} voltage", (Reg(H, 4358 + 2 * j, "u32be"),), "voltage", scale=0.1) for j, x in enumerate(ph)],
        *[Field(f"current_{x}", f"Phase {x.upper()} current", (Reg(H, 4364 + 2 * j, "u32be"),), "current", scale=0.01) for j, x in enumerate(ph)],
        Field("active_power", "Grid power", (Reg(H, 4370, "s32be"),), "power", "fast", attrs={"sign": "positive = import"}),
        *[Field(f"active_power_{x}", f"Phase {x.upper()} power", (Reg(H, 4372 + 2 * j, "s32be"),), "power", "fast") for j, x in enumerate(ph)],
        Field("reactive_power", "Reactive power", (Reg(H, 4378, "s32be"),), "reactive_power"),
        *[Field(f"reactive_power_{x}", f"Phase {x.upper()} reactive power", (Reg(H, 4380 + 2 * j, "s32be"),), "reactive_power") for j, x in enumerate(ph)],
        Field("apparent_power", "Apparent power", (Reg(H, 4386, "u32be"),), "apparent_power"),
        *[Field(f"apparent_power_{x}", f"Phase {x.upper()} apparent power", (Reg(H, 4388 + 2 * j, "u32be"),), "apparent_power") for j, x in enumerate(ph)],
        Field("power_factor", "Power factor", (Reg(H, 4394, "s32be"),), "power_factor", scale=0.001),
        *[Field(f"power_factor_{x}", f"Phase {x.upper()} power factor", (Reg(H, 4396 + 2 * j, "s32be"),), "power_factor", scale=0.001) for j, x in enumerate(ph)],
        Field("frequency", "Frequency", (Reg(H, 4420, "s32be"),), "frequency", scale=0.01),
        Field("total_energy", "Total energy", (Reg(H, 4608, "u32be"),), "energy", scale=0.01),
    ]


LOGGER_TYPE = {0x0705: "Logger3000", 0x0718: "Logger4000", 0x0710: "Logger1000A/B", 0x071E: "Logger1000A-EU"}
LOGGER_EMS = {1: "Self-consumption", 5: "Forced mode", 4: "VPP"}
LOGGER_CMD = {0xAA: "Charge", 0xBB: "Discharge", 0xCC: "Stop"}


def logger() -> list[Field]:
    """The Logger1000A itself (unit 247): site totals across both inverters."""
    return [
        Field("device_type", "Model", (Reg(I, 7999, "u16"),), "enum", "static", options=LOGGER_TYPE, category="diagnostic"),
        Field("devices_connected", "Devices connected", (Reg(I, 8004, "u16"),), "count", "slow", category="diagnostic"),
        Field("devices_faulty", "Faulty devices", (Reg(I, 8005, "u16"),), "count", "slow", category="diagnostic"),
        Field("max_nominal_power", "Max total nominal active power", (Reg(I, 8057, "s16"),), "power", "static", scale=1000, category="diagnostic"),
        Field("state", "State", (Reg(I, 8067, "u16"),), "count", "slow", category="diagnostic"),
        Field("daily_yield", "Daily yield", (Reg(I, 8073, "u32"),), "energy", "slow", scale=0.1),
        Field("total_reactive_power", "Total reactive power", (Reg(I, 8075, "s64be"),), "reactive_power", "slow"),
        Field("total_yield", "Total yield", (Reg(I, 8079, "u64be"),), "energy", "slow", scale=0.1),
        Field("nominal_power", "Total nominal active power", (Reg(I, 8144, "u32"),), "power", "static", scale=100, category="diagnostic"),
        Field("battery_rated_capacity", "Total battery rated capacity", (Reg(I, 8146, "u32"),), "energy_storage", "static", scale=0.1, category="diagnostic"),
        Field("battery_max_charge_power", "Battery max allowable charge power", (Reg(I, 8150, "u16"),), "power", "slow", scale=100, category="diagnostic"),
        Field("battery_min_charge_power", "Battery min allowable charge power", (Reg(I, 8151, "u16"),), "power", "slow", scale=100, category="diagnostic"),
        Field("battery_max_discharge_power", "Battery max allowable discharge power", (Reg(I, 8152, "u16"),), "power", "slow", scale=100, category="diagnostic"),
        Field("battery_min_discharge_power", "Battery min allowable discharge power", (Reg(I, 8153, "u16"),), "power", "slow", scale=100, category="diagnostic"),
        # the whole site in one 9-register block: the fastest view of the system
        Field("total_active_power", "Total active power", (Reg(I, 8154, "s32"),), "power", "fast", scale=10),
        Field("grid_power", "Grid power", (Reg(I, 8156, "s32"),), "power", "fast", scale=10),
        Field("load_power", "Load power", (Reg(I, 8158, "s32"),), "power", "fast", scale=10),
        Field("battery_power", "Battery power", (Reg(I, 8160, "s32"),), "power", "fast", scale=10),
        Field("battery_level", "Battery level", (Reg(I, 8162, "u16"),), "battery", "fast", scale=0.1),
        Field("daily_battery_charge", "Daily battery charge", (Reg(I, 8163, "u32"),), "energy", "slow", scale=0.1),
        Field("daily_battery_discharge", "Daily battery discharge", (Reg(I, 8165, "u32"),), "energy", "slow", scale=0.1),
        Field("total_battery_charge", "Total battery charge", (Reg(I, 8167, "u64be"),), "energy", "slow", scale=0.1),
        Field("total_battery_discharge", "Total battery discharge", (Reg(I, 8171, "u64be"),), "energy", "slow", scale=0.1),
        Field("grid_import_energy", "Grid import energy", (Reg(I, 8175, "u32"),), "energy", "slow", scale=0.1),
        Field("grid_export_energy", "Grid export energy", (Reg(I, 8177, "u32"),), "energy", "slow", scale=0.1),
        # settings
        Field("ems_mode", "EMS mode", (Reg(H, 8023, "u16"),), "enum", "setting", options=LOGGER_EMS, category="config"),
        Field("command", "Charge/discharge command", (Reg(H, 8024, "u16"),), "enum", "setting", options=LOGGER_CMD, category="config"),
        Field("command_power", "Charge/discharge power", (Reg(H, 8025, "u32"),), "power", "setting", scale=100, category="config"),
        Field("feed_in_limitation", "Feed-in limitation", (Reg(H, 8027, "u16"),), "count", "setting", category="config"),
        Field("feed_in_limit", "Feed-in limit", (Reg(H, 8028, "s32"),), "power", "setting", scale=100, category="config"),
        Field("vpp_heartbeat", "VPP heartbeat", (Reg(H, 8032, "u16"),), "duration", "setting", category="config"),
    ]


LOGGER_CONTROLS: dict[str, dict[str, Any]] = {
    "ems_mode": {"kind": "select"},
    "command": {"kind": "select"},
    "command_power": {"kind": "number", "min": 0, "max_key": "nominal_power", "step": 100},
    "feed_in_limit": {"kind": "number", "min": 0, "max_key": "nominal_power", "step": 100},
}


TOWER_TYPE = {
    0x20E6: "SBR064", 0x20E7: "SBR096", 0x20E8: "SBR128", 0x20E9: "SBR160", 0x20EA: "SBR192",
    0x20EB: "SBR224", 0x20EC: "SBR256", 0x20F1: "SBH100", 0x20F2: "SBH150", 0x20F3: "SBH200",
    0x20F4: "SBH250", 0x20F5: "SBH300", 0x20F6: "SBH300", 0x20F7: "SBH350", 0x20F8: "SBH350",
}
TOWER_STATUS = {0: "Unplugged", 1: "Standby", 2: "Run"}


def tower() -> list[Field]:
    """One battery tower's BMS behind the Logger. Cell and module data (10757+) is refused by the Logger."""


    return [
        Field("type", "Model", (Reg(I, 10709, "u16"),), "enum", "static", options=TOWER_TYPE, category="diagnostic"),
        Field("serial", "Serial number", (Reg(I, 10710, "str10"),), "text", "static", category="diagnostic"),
        Field("firmware", "Firmware", (Reg(I, 10720, "str10"),), "text", "static", category="diagnostic"),
        Field("status", "Status", (Reg(I, 10739, "u16"),), "enum", options=TOWER_STATUS),
        Field("voltage", "Voltage", (Reg(I, 10740, "u16"),), "voltage", scale=0.1),
        Field("current", "Current", (Reg(I, 10741, "s16"),), "current", scale=0.1),
        Field("level", "Battery level", (Reg(I, 10743, "u16"),), "battery", scale=0.1),
        Field("soh", "State of health", (Reg(I, 10744, "u16"),), "percent", "slow"),
        Field("total_charge", "Total charge", (Reg(I, 10745, "u32"),), "energy", "slow", scale=0.1),
        Field("total_discharge", "Total discharge", (Reg(I, 10747, "u32"),), "energy", "slow", scale=0.1),
        # Through a Logger1000 this register holds a fixed 14 °C on SBR and SBH alike (unchanged for
        # weeks while the inverters' battery temperature moves; 9 Nov 2026): kept for whoever has a
        # path that fills it, hidden and disabled by default, never shown as the tower's temperature.
        Field("temperature", "Temperature register (fixed)", (Reg(I, 10750, "s16"),), "temperature",
              category="diagnostic", enabled=False),
    ]


#: device key -> (Logger port, unit, device name, fields)
# --- devices -------------------------------------------------------------------
# What a device is, never where: the integration finds each one on the Logger
# (discovery.py) and keeps the list in its config entry.

KIND_NAMES = {"inverter": "Sungrow inverter", "meter": "Sungrow grid meter", "logger": "Sungrow Logger", "tower": "Sungrow battery tower"}
#: kinds a site has at most one of: their key and name carry no number
SINGLE = ("meter", "logger")


@dataclass(frozen=True)
class Device:
    key: str  # "inverter_1", "tower_3", "meter", "logger": the entity ids' stem
    kind: str
    port: int
    unit: int
    name: str
    model: str | None = None
    serial: str | None = None
    #: a tower: the key of the inverter whose battery stack it is part of, when known
    inverter: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Device:
        return cls(**{k: d.get(k) for k in ("key", "kind", "port", "unit", "name", "model", "serial", "inverter")})


def device(kind: str, number: int, port: int, unit: int, **kw: Any) -> Device:
    """A device of `kind`, numbered `number` among its kind (ignored for the single kinds)."""
    if kind not in KIND_NAMES:
        raise ValueError(f"unknown device kind {kind!r}")
    key = kind if kind in SINGLE else f"{kind}_{number}"
    name = KIND_NAMES[kind] if kind in SINGLE else f"{KIND_NAMES[kind]} {number}"
    return Device(key, kind, int(port), int(unit), name, **kw)


def fields_for(kind: str) -> list[Field]:
    """Every field a device of this kind has (a fresh list)."""
    if kind == "inverter":
        return _with_controls(inverter(), INVERTER_CONTROLS)
    if kind == "logger":
        return _with_controls(logger(), LOGGER_CONTROLS)
    if kind == "meter":
        return meter()
    if kind == "tower":
        return tower()
    raise ValueError(f"unknown device kind {kind!r}")


def table(devices: list[Device]) -> dict[str, tuple[int, int, str, list[Field]]]:
    """key -> (port, unit, name, fields) for a list of devices."""
    return {d.key: (d.port, d.unit, d.name, fields_for(d.kind)) for d in devices}

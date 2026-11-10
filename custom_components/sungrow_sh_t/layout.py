from __future__ import annotations

import re
from typing import Any

INV: tuple[int, ...] = ()
TOWERS: tuple[int, ...] = ()
PH = "abc"
I: list[str] = []
AMBER, TEAL, BLUE, LILAC = "#F2A93B", "#22B5A6", "#5B8DEF", "#9B87F5"

# Green = the function is on, red = it is off (Enabled/Disabled and On/Off need no table).
RUNNING = {"Shutdown": "off", "Self-consumption": "on", "Forced charge": "on", "Forced discharge": "on"}
FORCED = {"Stop": "off", "Forced charge": "on", "Forced discharge": "on", "Charge": "on", "Discharge": "on"}
SOLAR_LIMIT = {"Limit PV": "on", "Allow PV": "off"}


def inv(fmt: str) -> list[str]:
    return [fmt.format(n=n) for n in INV]


def row(label: str, entities: list, **kw) -> dict:
    return {"label": label, "entities": entities, **kw}


def group(title: str, columns: list[str] | None, rows: list[dict], **kw) -> dict:
    g = {"title": title, "rows": rows, **kw}
    if columns:
        g["columns"] = columns
    return g


def matrix(*groups) -> dict:
    return {"type": "custom:sungrow-matrix-card", "groups": list(groups)}


def item(span: int, *groups) -> dict:
    """One column of the page: `span` of 4 tracks, its groups stacked top to bottom."""
    return {"span": span, "groups": list(groups)}


def page(*rows) -> dict:
    """A page as deliberate rows; each row is a list of items."""
    return {"type": "custom:sungrow-matrix-card", "layout": [list(r) for r in rows]}


def kpis(title: str, *items) -> dict:
    return {"title": title, "kpis": list(items)}


def kpi(label: str, entity: str | None = None, *, sum: list[str] | None = None, color: str | None = None, digits: int = 2, tones: dict | None = None) -> dict:
    k = {"label": label, "digits": digits}
    if tones:
        k["tones"] = tones
    if sum:
        k["sum"] = sum
    else:
        k["entity"] = entity
    if color:
        k["color"] = color
    return k


def flow() -> dict:
    return {
        "type": "custom:sungrow-flow-card", "needs": "sensor.sungrow_logger_battery_level",
        "pv": inv("sensor.sungrow_inverter_{n}_pv_power"), "home": "sensor.sungrow_logger_load_power", "grid": "sensor.sungrow_logger_grid_power",
        "battery": "sensor.sungrow_logger_battery_power", "soc": "sensor.sungrow_logger_battery_level",
        "towers": [f"sensor.sungrow_battery_tower_{t}_battery_level" for t in TOWERS], "mode": "select.sungrow_logger_ems_mode",
    }
FLAGS = [("pv_generating", "PV generating"), ("battery_charging", "Battery charging"), ("battery_discharging", "Battery discharging"),
         ("powering_loads", "Powering loads"), ("exporting_power", "Exporting"), ("importing_power", "Importing"), ("loads_generating", "Loads generating")]


# --- charts ------------------------------------------------------------------
PHASE = {"a": "#EF6461", "b": "#E8C547", "c": "#5B8DEF"}  # red, white (shown amber), blue
_TOWER_COLORS = (TEAL, BLUE, AMBER, LILAC, "#EF6461", "#E8C547")
_INV_COLORS = (AMBER, TEAL, BLUE, LILAC, "#EF6461", "#E8C547")


def tower_color(t: int) -> str:
    return _TOWER_COLORS[(t - 1) % len(_TOWER_COLORS)]


def inv_color(n: int) -> str:
    return _INV_COLORS[(n - 1) % len(_INV_COLORS)]


def s(entity: str, label: str, color: str, **kw) -> dict:
    return {"entity": entity, "label": label, "color": color, **kw}


def chart(title: str, color: str, ranges: list[str], views: list[dict], **kw) -> dict:
    return {"title": title, "color": color, "ranges": ranges, "views": views, **kw}


def view(name: str, unit: str, series: list[dict], **kw) -> dict:
    return {"name": name, "unit": unit, "series": series, **kw}


def charts(*cs) -> dict:
    return {"type": "custom:sungrow-charts", "charts": list(cs)}


def battery_charts() -> dict:
    soc = chart("State of charge", TEAL, ["24h", "7d", "60d", "360d"], [view("", "%", [
        s("sensor.sungrow_logger_battery_level", "Site", "#8a93a3", area=True),
        *(s(f"sensor.sungrow_inverter_{n}_battery_level", f"Inverter {n}", inv_color(n)) for n in INV),
    ], min=0, max=100)])
    first = INV[0] if INV else 1
    bands = [{"entity": f"binary_sensor.sungrow_inverter_{first}_battery_{k}_60_s", "label": label, "color": c}
             for k, label, c in (("charging", "Charging", "#3FB37F"), ("discharging", "Discharging", "#EF6461"))]
    towers = chart("Battery towers", TEAL, ["24h", "7d", "60d"], [
        view("Charge", "%", [s(f"sensor.sungrow_battery_tower_{t}_battery_level", f"Tower {t}", tower_color(t)) for t in TOWERS], bands=bands, min=0, max=100),
        view("Current", "A", [s(f"sensor.sungrow_battery_tower_{t}_current", f"Tower {t}", tower_color(t)) for t in TOWERS], bands=bands, zero=True),
        view("Voltage", "V", [s(f"sensor.sungrow_battery_tower_{t}_voltage", f"Tower {t}", tower_color(t)) for t in TOWERS]),
        view("Health", "%", [s(f"sensor.sungrow_battery_tower_{t}_state_of_health", f"Tower {t}", tower_color(t)) for t in TOWERS]),
    ])
    return charts(soc, towers)


def solar_charts() -> dict:
    power = chart("Inverter power", AMBER, ["6h", "24h", "7d"], [
        view(f"Inverter {n}", "kW", [
            s(f"sensor.sungrow_inverter_{n}_pv_power", "Solar", AMBER, area=True),
            s(f"sensor.sungrow_inverter_{n}_active_power", "AC output", BLUE),
            s(f"sensor.sungrow_inverter_{n}_battery_power", "Battery", TEAL),
        ], zero=True) for n in INV])
    mppt = ["#F2A93B", "#EF6461", "#9B87F5"]
    strings = ["#F2A93B", "#EF6461", "#9B87F5", "#5B8DEF", "#22B5A6"]
    pv = chart("MPPTs and strings", AMBER, ["24h", "7d"], [
        view("MPPTs", "kW", [s(f"sensor.sungrow_inverter_{n}_mppt{m}_power", f"Inv {n} MPPT {m}", mppt[m - 1], dash=n % 2 == 0) for n in INV for m in (1, 2, 3)], min=0),
        *(view(f"Inverter {n} strings", "kW", [s(f"sensor.sungrow_inverter_{n}_string_{k}_power", f"String {k}", strings[k - 1]) for k in range(1, 6)], min=0) for n in INV),
    ])
    limits = chart("Limits against what happened", "#EF6461", ["24h", "7d"], [
        *(view(f"Inverter {n}", "kW", [
            s(f"sensor.sungrow_inverter_{n}_active_power", "AC output", BLUE, area=True),
            s(f"number.sungrow_inverter_{n}_active_power_limit", "Output limit", "#EF6461", step=True, dash=True),
            s(f"number.sungrow_inverter_{n}_export_power_limit", "Export limit", "#E8C547", step=True, dash=True),
        ], min=0) for n in INV),
        view("Site", "kW", [
            s("sensor.sungrow_logger_grid_power", "Export", "#3FB37F", area=True, scale=-1),
            s("number.sungrow_logger_feed_in_limit", "Feed-in limit", "#EF6461", step=True, dash=True),
        ], zero=True),
    ], span=4)
    return charts(power, pv, limits)


def grid_charts() -> dict:
    power = chart("Grid power: Logger and meter", BLUE, ["6h", "24h", "7d"], [view("", "kW", [
        s("sensor.sungrow_grid_meter_grid_power", "Grid meter", BLUE),
        s("sensor.sungrow_logger_grid_power", "Logger", "#E8C547", dash=True),
    ], zero=True)], note="Positive: importing. Negative: exporting.")
    quality = chart("Grid voltage and frequency", BLUE, ["6h", "24h", "7d", "60d"], [
        view("Voltage", "V", [s(f"sensor.sungrow_grid_meter_phase_{p}_voltage", f"Phase {p.upper()}", PHASE[p]) for p in PH], refs=[
            {"value": 253, "label": "253 V upper", "color": "#EF6461"}, {"value": 230, "label": "230 V nominal", "color": "#8a93a3"}, {"value": 216, "label": "216 V lower", "color": "#EF6461"}]),
        view("Frequency", "Hz", [s("sensor.sungrow_grid_meter_frequency", "Grid", BLUE)], refs=[
            {"value": 50.15, "label": "50.15 Hz", "color": "#EF6461"}, {"value": 50, "label": "50 Hz", "color": "#8a93a3"}, {"value": 49.85, "label": "49.85 Hz", "color": "#EF6461"}]),
    ])
    return charts(power, quality)


def backup_charts() -> dict:
    return charts(chart("Backup output", TEAL, ["24h", "7d"], [
        *(view(f"Inverter {n} power", "kW", [s(f"sensor.sungrow_inverter_{n}_backup_phase_{p}_power", f"Phase {p.upper()}", PHASE[p], area=True) for p in PH], min=0) for n in INV),
        *(view(f"Inverter {n} voltage", "V", [s(f"sensor.sungrow_inverter_{n}_backup_phase_{p}_voltage", f"Phase {p.upper()}", PHASE[p]) for p in PH]) for n in INV),
    ], span=4))


def system_charts() -> dict:
    return charts(chart("Temperatures", AMBER, ["24h", "7d", "60d", "360d"], [
        view("Inverters and batteries", "°C", [
            *(s(f"sensor.sungrow_inverter_{n}_inverter_temperature", f"Inverter {n}", inv_color(n)) for n in INV),
            *(s(f"sensor.sungrow_inverter_{n}_battery_temperature", f"Battery {n}", inv_color(n), dash=True) for n in INV),
        ]),
    ], span=4))


def overview() -> dict:
    return {"id": "overview", "title": "Overview", "subtitle": "Live power through the house", "cards": [
        flow(),
        {"type": "custom:sungrow-day-card"},
        page([item(2, group("Inverters", I, [
                row("State", inv("sensor.sungrow_inverter_{n}_running_state")),
                row("EMS mode", inv("select.sungrow_inverter_{n}_ems_mode")),
                row("Solar", inv("sensor.sungrow_inverter_{n}_pv_power"), bar=True),
                row("Battery", inv("sensor.sungrow_inverter_{n}_battery_power")),
                row("Battery level", inv("sensor.sungrow_inverter_{n}_battery_level")),
                row("AC output", inv("sensor.sungrow_inverter_{n}_active_power")),
                row("Temperature", inv("sensor.sungrow_inverter_{n}_inverter_temperature")),
            ], color=AMBER)),
            item(1, group("Today", I, [
                row("Solar generated", inv("sensor.sungrow_inverter_{n}_daily_pv_generation"), bar=True),
                row("House used", inv("sensor.sungrow_inverter_{n}_daily_consumed_energy")),
                row("Imported", inv("sensor.sungrow_inverter_{n}_daily_import_energy")),
                row("Exported", inv("sensor.sungrow_inverter_{n}_daily_export_energy")),
                row("Battery charged", inv("sensor.sungrow_inverter_{n}_daily_battery_charge")),
                row("Battery discharged", inv("sensor.sungrow_inverter_{n}_daily_battery_discharge")),
                row("AC output", inv("sensor.sungrow_inverter_{n}_daily_output_energy")),
            ], color=LILAC)),
            item(1, group("What each inverter is doing", I, [row(label, inv(f"binary_sensor.sungrow_inverter_{{n}}_{k}")) for k, label in FLAGS], color=BLUE)),
        ]),
    ]}


def solar() -> dict:
    def column(n: int) -> dict:
        return item(4 if len(INV) == 1 else 2,
            group(f"Inverter {n} · DC side", [*[f"MPPT {m}" for m in (1, 2, 3)], *[f"S{k}" for k in range(1, 6)]], [
                row("Power", [*[f"sensor.sungrow_inverter_{n}_mppt{m}_power" for m in (1, 2, 3)], *[f"sensor.sungrow_inverter_{n}_string_{k}_power" for k in range(1, 6)]], bar=True),
                row("Voltage", [*[f"sensor.sungrow_inverter_{n}_mppt{m}_voltage" for m in (1, 2, 3)], *[f"sensor.sungrow_inverter_{n}_string_{k}_voltage" for k in range(1, 6)]]),
                row("Current", [*[f"sensor.sungrow_inverter_{n}_mppt{m}_current" for m in (1, 2, 3)], *[f"sensor.sungrow_inverter_{n}_string_{k}_current" for k in range(1, 6)]]),
            ], color=AMBER, dense=True, split_after=3),
            group(f"Inverter {n} · AC output", [p.upper() for p in PH], [
                row("Power", [f"sensor.sungrow_inverter_{n}_phase_{p}_power" for p in PH], bar=True),
                row("Voltage", [f"sensor.sungrow_inverter_{n}_phase_{p}_voltage" for p in PH]),
                row("Current", [f"sensor.sungrow_inverter_{n}_phase_{p}_current" for p in PH]),
            ], color=BLUE, dense=True),
        )

    return {"id": "solar", "title": "Solar", "subtitle": "Each inverter from panels to grid", "cards": [page(
        [item(4, dict(kpis("Solar now",
            kpi("Both inverters" if len(INV) == 2 else "All inverters" if len(INV) > 1 else "Solar", sum=inv("sensor.sungrow_inverter_{n}_pv_power"), color=AMBER),
            *(kpi(f"Inverter {n}", f"sensor.sungrow_inverter_{n}_pv_power") for n in INV),
            kpi("Today, both" if len(INV) == 2 else "Today, all" if len(INV) > 2 else "Today", sum=inv("sensor.sungrow_inverter_{n}_daily_pv_generation"), digits=1),
            *(kpi(f"Inverter {n} today", f"sensor.sungrow_inverter_{n}_daily_pv_generation", digits=1) for n in INV),
            *(kpi(f"Inverter {n} lifetime", f"sensor.sungrow_inverter_{n}_total_pv_generation", digits=0) for n in INV),
            *(kpi(f"Inverter {n} solar limit", f"select.sungrow_inverter_{n}_pv_power_limitation", tones=SOLAR_LIMIT) for n in INV),
        ), color=AMBER))],
        [column(n) for n in INV],
        [item(2, group("Curtailment · solar and export", I, [
            row("Solar limit", inv("select.sungrow_inverter_{n}_pv_power_limitation"), tones=SOLAR_LIMIT),
            row("Export limit", inv("select.sungrow_inverter_{n}_feed_in_limitation")),
            row("Export limit, kW", inv("number.sungrow_inverter_{n}_export_power_limit")),
            row("Export limit, %", inv("number.sungrow_inverter_{n}_feed_in_limitation_ratio")),
            row("Export limit mode", inv("select.sungrow_inverter_{n}_export_limit_mode")),
        ], color="#EF6461", dense=True)),
         item(2, group("Curtailment · inverter output", I, [
            row("Output limit", inv("select.sungrow_inverter_{n}_active_power_limitation")),
            row("Output limit, %", inv("number.sungrow_inverter_{n}_active_power_limit_ratio")),
            row("Output limit, kW", inv("number.sungrow_inverter_{n}_active_power_limit")),
            row("Shut down at 0 %", inv("select.sungrow_inverter_{n}_shut_down_at_0_power_limit")),
        ], color="#EF6461", dense=True))],
    )]}


def battery() -> dict:
    T = [f"Tower {t}" for t in TOWERS]
    return {"id": "battery", "title": "Battery", "subtitle": "The whole battery, each inverter and each tower", "cards": [
        {"type": "custom:sungrow-battery-card", "towers": list(TOWERS), "needs": "sensor.sungrow_logger_battery_level"},
        page(
            [item(4, group("Towers", T, [
                row("Status", [f"sensor.sungrow_battery_tower_{t}_status" for t in TOWERS]),
                row("Level", [f"sensor.sungrow_battery_tower_{t}_battery_level" for t in TOWERS], bar=True),
                row("Voltage", [f"sensor.sungrow_battery_tower_{t}_voltage" for t in TOWERS]),
                row("Current", [f"sensor.sungrow_battery_tower_{t}_current" for t in TOWERS]),
                row("Health", [f"sensor.sungrow_battery_tower_{t}_state_of_health" for t in TOWERS]),
                row("Charged, lifetime", [f"sensor.sungrow_battery_tower_{t}_total_charge" for t in TOWERS]),
                row("Discharged, lifetime", [f"sensor.sungrow_battery_tower_{t}_total_discharge" for t in TOWERS]),
                *([row("Temperature", [f"sensor.sungrow_inverter_{STACKS[t][0]}_battery_temperature" if t in STACKS else None for t in TOWERS],
                       subs=[f"stack, from {STACKS[t][1]}" if t in STACKS else "" for t in TOWERS])] if STACKS else []),
            ], color=TEAL, dense=True, note="Cell and module voltages are not available over Modbus: the Logger refuses those registers. A tower’s own temperature register reads a fixed 14 °C through a Logger1000, so each tower shows its battery stack’s temperature, as its inverter measures it."))],
            [item(2, group("Each inverter's battery", I, [
                row("Level", inv("sensor.sungrow_inverter_{n}_battery_level"), bar=True),
                row("Level, nominal", inv("sensor.sungrow_inverter_{n}_battery_level_nominal")),
                row("Power", inv("sensor.sungrow_inverter_{n}_battery_power")),
                row("Charging", inv("sensor.sungrow_inverter_{n}_battery_charging_power")),
                row("Discharging", inv("sensor.sungrow_inverter_{n}_battery_discharging_power")),
                row("Voltage", inv("sensor.sungrow_inverter_{n}_battery_voltage")),
                row("Current", inv("sensor.sungrow_inverter_{n}_battery_current")),
                row("Temperature", inv("sensor.sungrow_inverter_{n}_battery_temperature")),
                row("Health", inv("sensor.sungrow_inverter_{n}_battery_state_of_health")),
                row("Capacity", inv("sensor.sungrow_inverter_{n}_battery_capacity")),
                row("Stored", inv("sensor.sungrow_inverter_{n}_battery_charge")),
                row("Stored, nominal", inv("sensor.sungrow_inverter_{n}_battery_charge_nominal")),
                row("Stored, health-rated", inv("sensor.sungrow_inverter_{n}_battery_charge_health_rated")),
                row("BMS max charge current", inv("sensor.sungrow_inverter_{n}_bms_max_charge_current")),
                row("BMS max discharge current", inv("sensor.sungrow_inverter_{n}_bms_max_discharge_current")),
            ], color=TEAL, dense=True)),
            item(2, group("Limits", I, [
                row("Min SoC", inv("number.sungrow_inverter_{n}_min_soc")),
                row("Max SoC", inv("number.sungrow_inverter_{n}_max_soc")),
                row("Max charge power", inv("number.sungrow_inverter_{n}_max_battery_charge_power")),
                row("Max discharge power", inv("number.sungrow_inverter_{n}_max_battery_discharge_power")),
            ], color="#EF6461"),
            group("Whole battery (Logger)", None, [
                row("Rated capacity", ["sensor.sungrow_logger_total_battery_rated_capacity"]),
                row("Can charge at", ["sensor.sungrow_logger_battery_max_allowable_charge_power"]),
                row("Can discharge at", ["sensor.sungrow_logger_battery_max_allowable_discharge_power"]),
                row("Min charge power", ["sensor.sungrow_logger_battery_min_allowable_charge_power"]),
                row("Min discharge power", ["sensor.sungrow_logger_battery_min_allowable_discharge_power"]),
            ], color=TEAL))],
            [item(4, group("Battery energy", [*I, "Site"], [
                row("Charged today", [*inv("sensor.sungrow_inverter_{n}_daily_battery_charge"), "sensor.sungrow_logger_daily_battery_charge"]),
                row("Discharged today", [*inv("sensor.sungrow_inverter_{n}_daily_battery_discharge"), "sensor.sungrow_logger_daily_battery_discharge"]),
                row("Charged, lifetime", [*inv("sensor.sungrow_inverter_{n}_total_battery_charge"), "sensor.sungrow_logger_total_battery_charge"]),
                row("Discharged, lifetime", [*inv("sensor.sungrow_inverter_{n}_total_battery_discharge"), "sensor.sungrow_logger_total_battery_discharge"]),
            ], color=TEAL))],
        ),
    ]}


def grid() -> dict:
    P = [f"Phase {p.upper()}" for p in PH]
    return {"id": "grid", "title": "Grid", "subtitle": "The grid meter, phase by phase", "cards": [
        {"type": "custom:sungrow-grid-card", "needs": "sensor.sungrow_grid_meter_grid_power"},
        page(
            [item(2, group("Per phase", P, [
                row("Power", [f"sensor.sungrow_grid_meter_phase_{p}_power" for p in PH], bar=True),
                row("Voltage", [f"sensor.sungrow_grid_meter_phase_{p}_voltage" for p in PH]),
                row("Current", [f"sensor.sungrow_grid_meter_phase_{p}_current" for p in PH]),
                row("Power factor", [f"sensor.sungrow_grid_meter_phase_{p}_power_factor" for p in PH]),
                row("Reactive power", [f"sensor.sungrow_grid_meter_phase_{p}_reactive_power" for p in PH]),
                row("Apparent power", [f"sensor.sungrow_grid_meter_phase_{p}_apparent_power" for p in PH]),
                row("Line voltage", ["sensor.sungrow_grid_meter_line_voltage_a_b", "sensor.sungrow_grid_meter_line_voltage_b_c", "sensor.sungrow_grid_meter_line_voltage_c_a"]),
            ], color=BLUE, corner="", note="Line voltages: A–B, B–C, C–A.")),
            item(1, group("Meter", None, [
                row("Grid power", ["sensor.sungrow_grid_meter_grid_power"]),
                row("Frequency", ["sensor.sungrow_grid_meter_frequency"]),
                row("Power factor", ["sensor.sungrow_grid_meter_power_factor"]),
                row("Reactive power", ["sensor.sungrow_grid_meter_reactive_power"]),
                row("Apparent power", ["sensor.sungrow_grid_meter_apparent_power"]),
                row("Meter total", ["sensor.sungrow_grid_meter_total_energy"]),
                row("Site AC power (Logger)", ["sensor.sungrow_logger_total_active_power"]),
            ], color=BLUE)),
            item(1, group("Grid limits", ["Inv 1", "Inv 2"], [
                row("Export", inv("number.sungrow_inverter_{n}_export_power_limit")),
                row("Fallback", inv("number.sungrow_inverter_{n}_export_limit_fallback")),
                row("Import", inv("number.sungrow_inverter_{n}_site_import_limit")),
            ], color="#EF6461", dense=True), group("Site feed-in limit (Logger)", None, [
                row("Export", ["number.sungrow_logger_feed_in_limit"]),
            ], color="#EF6461", dense=True))],
            [item(4, group("Grid energy", [*I, "Site"], [
                row("Imported today", [*inv("sensor.sungrow_inverter_{n}_daily_import_energy"), None]),
                row("Exported today", [*inv("sensor.sungrow_inverter_{n}_daily_export_energy"), None]),
                row("Imported, lifetime", [*inv("sensor.sungrow_inverter_{n}_total_import_energy"), "sensor.sungrow_logger_grid_import_energy"]),
                row("Exported, lifetime", [*inv("sensor.sungrow_inverter_{n}_total_export_energy"), "sensor.sungrow_logger_grid_export_energy"]),
                row("House used, lifetime", [*inv("sensor.sungrow_inverter_{n}_total_consumed_energy"), None]),
            ], color=BLUE))],
        ),
    ]}


def backup() -> dict:
    groups = [group("Whole-home backup", I, [
        row("Backup", inv("select.sungrow_inverter_{n}_backup_off_grid_option")),
        row("Reserve", inv("number.sungrow_inverter_{n}_reserved_soc_for_backup")),
        row("Backup power", inv("sensor.sungrow_inverter_{n}_backup_power"), bar=True),
        row("Frequency", inv("sensor.sungrow_inverter_{n}_backup_frequency")),
        {"label": "Backup, both inverters", "sum": inv("sensor.sungrow_inverter_{n}_backup_power")},
        {"label": "House, whole (Logger)", "sum": ["sensor.sungrow_logger_load_power"]},
    ], color=TEAL, wide=True, note="Backup carries only the circuits wired to the backup ports; the rest of the house is supplied directly.")]
    for n in INV:
        groups.append(group(f"Inverter {n} · backup output", [p.upper() for p in PH], [
            row("Power", [f"sensor.sungrow_inverter_{n}_backup_phase_{p}_power" for p in PH], bar=True),
            row("Voltage", [f"sensor.sungrow_inverter_{n}_backup_phase_{p}_voltage" for p in PH]),
            row("Current", [f"sensor.sungrow_inverter_{n}_backup_phase_{p}_current" for p in PH]),
        ], color=TEAL))
    return {"id": "backup", "title": "Backup", "subtitle": "Whole-home backup output", "cards": [matrix(*groups)]}


def controls() -> dict:
    gs = [
        group("Site (Logger)", None, [
            row("EMS mode", ["select.sungrow_logger_ems_mode"]),
            row("Charge / discharge", ["select.sungrow_logger_charge_discharge_command"], tones=FORCED),
            row("Charge / discharge power", ["number.sungrow_logger_charge_discharge_power"]),
            row("Feed-in limit", ["number.sungrow_logger_feed_in_limit"]),
        ], color=BLUE),
        group("Mode", I, [
            row("System mode", inv("select.sungrow_inverter_{n}_system_mode"), tones=RUNNING),
            row("EMS mode", inv("select.sungrow_inverter_{n}_ems_mode")),
            row("Forced charge / discharge", inv("select.sungrow_inverter_{n}_forced_charge_discharge"), tones=FORCED),
            row("Forced power", inv("number.sungrow_inverter_{n}_forced_charge_discharge_power")),
        ], color=BLUE),
        group("Curtailment", I, [
            row("Solar limit", inv("select.sungrow_inverter_{n}_pv_power_limitation"), tones=SOLAR_LIMIT),
            row("Export limit", inv("select.sungrow_inverter_{n}_feed_in_limitation")),
            row("Export limit, kW", inv("number.sungrow_inverter_{n}_export_power_limit")),
            row("Export limit, %", inv("number.sungrow_inverter_{n}_feed_in_limitation_ratio")),
            row("Export limit mode", inv("select.sungrow_inverter_{n}_export_limit_mode")),
            row("Output limit", inv("select.sungrow_inverter_{n}_active_power_limitation")),
            row("Output limit, kW", inv("number.sungrow_inverter_{n}_active_power_limit")),
            row("Output limit, %", inv("number.sungrow_inverter_{n}_active_power_limit_ratio")),
            row("Shut down at 0 %", inv("select.sungrow_inverter_{n}_shut_down_at_0_power_limit")),
        ], color="#EF6461"),
        group("Battery and backup", I, [
            row("Min SoC", inv("number.sungrow_inverter_{n}_min_soc")),
            row("Max SoC", inv("number.sungrow_inverter_{n}_max_soc")),
            row("Max charge power", inv("number.sungrow_inverter_{n}_max_battery_charge_power")),
            row("Max discharge power", inv("number.sungrow_inverter_{n}_max_battery_discharge_power")),
            row("Backup", inv("select.sungrow_inverter_{n}_backup_off_grid_option")),
            row("Backup reserve", inv("number.sungrow_inverter_{n}_reserved_soc_for_backup")),
        ], color=TEAL),
        group("Grid limits", I, [
            row("Site import limit", inv("number.sungrow_inverter_{n}_site_import_limit")),
        ], color="#EF6461"),
        group("Inverter trims: ramp rates and fallbacks", I, [
            row("Power rising gradient", inv("number.sungrow_inverter_{n}_power_rising_gradient")),
            row("Power decline gradient", inv("number.sungrow_inverter_{n}_power_decline_gradient")),
            row("Rising, fallback", inv("number.sungrow_inverter_{n}_power_rising_gradient_fallback")),
            row("Decline, fallback", inv("number.sungrow_inverter_{n}_power_decline_gradient_fallback")),
            row("Export, fallback", inv("number.sungrow_inverter_{n}_export_limit_fallback")),
        ], color="#EF6461"),
    ]
    site, mode, curtail, battery, limits, trims = gs
    for g in gs:
        g["dense"] = True
    return {"id": "controls", "title": "Controls", "subtitle": "Every setting, written and read back · green on, red off", "cards": [page(
        [item(1, site, trims), item(1, battery, limits), item(2, mode, curtail)],
    )]}


def system() -> dict:
    inverters = group("Inverters", I, [
        row("Model", inv("sensor.sungrow_inverter_{n}_model")),
        row("Serial", inv("sensor.sungrow_inverter_{n}_serial_number")),
        row("Rated output", inv("sensor.sungrow_inverter_{n}_rated_output_power")),
        row("AC output, lifetime", inv("sensor.sungrow_inverter_{n}_total_output_energy")),
        row("Battery converter", inv("sensor.sungrow_inverter_{n}_battery_converter_rated_power")),
        row("Temperature", inv("sensor.sungrow_inverter_{n}_inverter_temperature")),
        row("Grid frequency", inv("sensor.sungrow_inverter_{n}_grid_frequency")),
        row("Power factor", inv("sensor.sungrow_inverter_{n}_power_factor")),
        row("Reactive power", inv("sensor.sungrow_inverter_{n}_reactive_power")),
        row("Export limit, min", inv("sensor.sungrow_inverter_{n}_export_limit_minimum")),
        row("Export limit, max", inv("sensor.sungrow_inverter_{n}_export_limit_maximum")),
    ], color=AMBER, dense=True)
    towers = group("Towers", ["Model", "Serial", "Firmware"], [
        row(f"Tower {t}", [f"sensor.sungrow_battery_tower_{t}_model", f"sensor.sungrow_battery_tower_{t}_serial_number", f"sensor.sungrow_battery_tower_{t}_firmware"])
        for t in TOWERS
    ], color=TEAL, dense=True)
    flags = group("Power-flow flags, held 60 s", I, [row(label, inv(f"binary_sensor.sungrow_inverter_{{n}}_{k}_60_s")) for k, label in FLAGS], color=BLUE, dense=True)
    meter_in = group("Inverters' own meter input", I, [
        row("Meter power", inv("sensor.sungrow_inverter_{n}_meter_active_power")),
        row("Load power", inv("sensor.sungrow_inverter_{n}_load_power")),
        row("Import power", inv("sensor.sungrow_inverter_{n}_import_power")),
        row("Export power", inv("sensor.sungrow_inverter_{n}_export_power")),
        row("Frequency", inv("sensor.sungrow_inverter_{n}_meter_frequency")),
    ], dim=True, dense=True, note="Not connected here: the grid meter is wired to the Logger.")
    meter_phases = group("Own meter input, per phase", [p.upper() for p in PH], [
        row(f"Inv {n} {q}", [f"sensor.sungrow_inverter_{n}_meter_phase_{p}_{q}" for p in PH]) for n in INV for q in ("power", "voltage", "current")
    ], dim=True, dense=True)
    logger = group("Logger", None, [
        row("Model", ["sensor.sungrow_logger_model"]),
        row("State", ["sensor.sungrow_logger_state"]),
        row("Devices connected", ["sensor.sungrow_logger_devices_connected"]),
        row("Faulty devices", ["sensor.sungrow_logger_faulty_devices"]),
        row("Nominal power", ["sensor.sungrow_logger_total_nominal_active_power"]),
        row("Max nominal power", ["sensor.sungrow_logger_max_total_nominal_active_power"]),
        row("VPP heartbeat", ["sensor.sungrow_logger_vpp_heartbeat"]),
        row("Feed-in limitation", ["sensor.sungrow_logger_feed_in_limitation"]),
        row("Yield today", ["sensor.sungrow_logger_daily_yield"]),
        row("Yield, lifetime", ["sensor.sungrow_logger_total_yield"]),
        row("Reactive power", ["sensor.sungrow_logger_total_reactive_power"]),
    ], color=BLUE, dense=True)
    return {"id": "system", "title": "System", "subtitle": "Devices, firmware and diagnostics", "cards": [page(
        [item(1, inverters), item(2, towers, {"pair": [flags, meter_in]}), item(1, logger, meter_phases)],
    )]}


def help_page() -> dict:
    """What is on right now (live, read only), then what every page and setting means."""
    ro = {"readonly": True}
    now = group("Right now: what is on", I, [
        row("System", inv("select.sungrow_inverter_{n}_system_mode"), tones=RUNNING, **ro),
        row("Forced charge / discharge", inv("select.sungrow_inverter_{n}_forced_charge_discharge"), tones=FORCED, **ro),
        row("Whole-home backup", inv("select.sungrow_inverter_{n}_backup_off_grid_option"), **ro),
        row("Solar limit", inv("select.sungrow_inverter_{n}_pv_power_limitation"), tones=SOLAR_LIMIT, **ro),
        row("Export limit", inv("select.sungrow_inverter_{n}_feed_in_limitation"), **ro),
        row("Export limit mode", inv("select.sungrow_inverter_{n}_export_limit_mode"), **ro),
        row("Output limit", inv("select.sungrow_inverter_{n}_active_power_limitation"), **ro),
        row("Shut down at 0 %", inv("select.sungrow_inverter_{n}_shut_down_at_0_power_limit"), **ro),
        row("EMS mode", inv("select.sungrow_inverter_{n}_ems_mode"), **ro),
    ], color=TEAL, note="Green: the function is on. Red: it is off. No colour: a mode, not an on/off switch. Change any of them on Controls.")
    site_now = group("Right now: the site (Logger)", None, [
        row("EMS mode", ["select.sungrow_logger_ems_mode"], **ro),
        row("Charge / discharge", ["select.sungrow_logger_charge_discharge_command"], tones=FORCED, **ro),
    ], color=BLUE)
    on, off = '<span class="on">Green</span>', '<span class="off">Red</span>'
    sections = [
        {"title": "Reading this dashboard", "color": TEAL, "text": [
            f"{on} means a function is <b>on</b>: backup enabled, an export or output limit in force, solar limited, the inverter running, a forced charge or discharge under way.",
            f"{off} means it is <b>off</b>: disabled, stopped, solar allowed, the inverter shut down. A mode such as EMS mode has no colour: it is a choice, not on or off.",
            "<b>not reported</b>: the device has not answered that register yet. <b>unavailable</b>: no fresh reading for three of its read intervals (at least 30 s).",
            "The dot at the top right is green while the house power keeps arriving, and red with the minutes since it stopped.",
            "Every setting is written, then read back from the device; the box shows what the device kept. If it refuses, the reason appears beside the box.",
        ]},
        {"title": "The pages", "color": AMBER, "table": {"head": ["Page", "What it shows"], "rows": [
            ["Overview", "Power flow through the house, today's energy, battery and towers"],
            ["Solar", "Each inverter's MPPTs and strings, and the solar and export limits"],
            ["Battery", "State of charge, the four towers, cell spread in mV, charge and discharge limits"],
            ["Grid", "The grid meter per phase, import and export, the grid limits"],
            ["Backup", "Whole-home backup output per inverter and phase"],
            ["Controls", "Every setting the inverters and the Logger accept"],
            ["System", "Models, serials, firmware, power-flow flags, diagnostics"],
        ]}},
        {"title": "Controls: what each one does", "color": "#EF6461", "wide": True, "text": [
            "Register numbers are Sungrow's protocol numbers, as the PDF lists them (on the wire each is one lower)."],
         "table": {"head": ["Control", "What it does", "Registers"], "reg": 2, "rows": [
            ["System mode", "Starts or shuts down the inverter, and sets EMS mode and command together: Shutdown, Self-consumption, Forced charge, Forced discharge", "13000, 13050, 13051"],
            ["EMS mode", "How the inverter decides: Self-consumption, Forced mode, External EMS (the Logger decides) or VPP", "13050"],
            ["Forced charge / discharge", "In Forced mode: Stop, Forced charge or Forced discharge", "13051"],
            ["Forced power", "The power of a forced charge or discharge", "13052"],
            ["Min SoC, Max SoC", "The battery's lower and upper limits", "13059, 13058"],
            ["Max charge / discharge power", "The battery's power limits", "33047, 33048"],
            ["Whole-home backup", "Whether the inverter carries the backup circuits through a grid outage", "13075"],
            ["Backup reserve", "State of charge kept back for an outage", "13100"],
            ["Solar limit", "Limit PV stops solar production; Allow PV lets it run", "13018"],
            ["Export limit", "Caps export to the grid at the export limit (kW or %)", "13087; 13074 kW, 13088 %"],
            ["Export limit mode", "Enabled (the total), Enabled per phase, or Disabled", "13087, 31226"],
            ["Output limit", "Caps the inverter's whole AC output (kW or %)", "31204, 31205"],
            ["Shut down at 0 %", "Whether a 0 % output limit shuts the inverter down", "31213"],
            ["Site import limit", "Caps power drawn from the grid", "32998"],
            ["Power rising / decline gradient", "How fast output may rise or fall (0-1200, in steps of 25)", "31202, 31201"],
            ["Fallbacks", "The protocol's fallback values for the export limit and both gradients", "31208, 31210, 31209"],
            ["Logger EMS mode, charge / discharge, power", "The same decisions for the whole site, through the Logger", "8024, 8025, 8026"],
            ["Logger feed-in limit", "The site's export cap", "8029"],
        ]}},
        {"title": "The integration's own settings", "color": BLUE, "text": [
            "Settings → Devices &amp; services → <b>Sungrow</b> → <b>Configure</b>:"],
         "table": {"head": ["Setting", "What it does"], "rows": [
            ["Read only", "Nothing is ever written to the inverters or the Logger; every control refuses"],
            ["Gentle pace", "Every reading ten times slower, for running beside another Modbus client on the same Logger"],
            ["Own entities", "This integration's own readings and controls (these pages). Off after a move from Modbus YAML, so the house starts with exactly the entities it had"],
        ]}},
        {"title": "Units", "color": LILAC, "text": [
            "Power in <b>kW</b> to 3 decimals (the inverter's 1 W resolution), energy in <b>kWh</b> to 1 decimal (the registers count 0.1 kWh), and the cell spread in <b>mV</b>, the only mV figure."]},
        {"title": "Something wrong?", "color": "#8a93a3", "text": [
            "Settings → System → <b>Logs</b>, search <code>sungrow_sh_t</code>: a refused register, a lost connection or a slow read is named there.",
            "If the dot at the top is red, the Logger is not answering: check it is powered and on the network.",
            'Report it at <a href="https://github.com/code-imstillalive/sungrow-alive/issues" target="_blank" rel="noopener">the integration\'s issues</a>, with the log lines.',
        ]},
    ]
    return {"id": "help", "title": "Help", "subtitle": "What is on, and what everything means", "cards": [
        page([item(3, now), item(1, site_now)]),
        {"type": "custom:sungrow-help-card", "sections": sections},
    ]}


def build(inverters: list[int], towers: list[int], stacks: dict[int, tuple[int, str]] | None = None) -> dict:
    """The dashboard for these inverter and tower numbers (as the devices' keys carry them). `stacks`:
    tower number -> (its inverter's number, that inverter's name or model), where known."""
    global INV, TOWERS, I, STACKS
    INV, TOWERS = tuple(sorted(inverters)), tuple(sorted(towers))
    STACKS = dict(stacks or {})
    I = [f"Inverter {n}" for n in INV]
    pages = [overview(), solar(), battery(), grid(), backup(), controls(), system(), help_page()]
    extra = {"battery": battery_charts, "solar": solar_charts, "grid": grid_charts, "backup": backup_charts, "system": system_charts}
    for pg in pages:  # each page's history charts sit under its tables
        if pg["id"] in extra:
            pg["cards"].append(extra[pg["id"]]())
    app = {"type": "custom:sungrow-app", "title": "Sungrow Alive", "pages": pages, "inverters": list(INV), "towers": list(TOWERS),
           "live": ["sensor.sungrow_logger_load_power", "sensor.sungrow_grid_meter_grid_power", *(f"sensor.sungrow_inverter_{n}_pv_power" for n in INV)]}
    return {"title": "Sungrow Alive", "views": [{"title": "Sungrow Alive", "path": "app", "icon": "mdi:solar-power-variant", "type": "panel", "cards": [app]}]}


_ID = re.compile(r"^(sensor|binary_sensor|number|select|switch)\.[a-z0-9_]+$")


def prune(node: Any, exists: set[str]) -> Any:
    """The same dashboard without what this site does not have: a missing entity in a table shows as a
    dash, a row, group, chart, tab, tile or page section with nothing left goes."""
    if isinstance(node, list):
        out = [prune(x, exists) for x in node]
        return [x for x in out if x is not _GONE]
    if not isinstance(node, dict):
        return node
    if "needs" in node and node["needs"] not in exists:  # a designed card built around one reading
        return _GONE
    if "entities" in node and "label" in node:  # a table row: keep its columns, blank the missing
        ents = [e if e in exists else None for e in node["entities"]]
        return {**node, "entities": ents} if any(ents) else _GONE
    if "sum" in node and "label" in node:
        ids = [e for e in node["sum"] if e in exists]
        return {**node, "sum": ids} if ids else _GONE
    if "entity" in node and ("label" in node or "color" in node) and isinstance(node["entity"], str) and _ID.match(node["entity"]):
        return node if node["entity"] in exists else _GONE  # a kpi, a series or a band
    out = {}
    for k, v in node.items():
        if isinstance(v, str) and _ID.match(v) and k not in ("type",):
            out[k] = v if v in exists else None
        elif isinstance(v, list) and v and all(isinstance(x, str) and _ID.match(x) for x in v):
            out[k] = [x for x in v if x in exists]
        else:
            pv = prune(v, exists)
            if pv is not _GONE:
                out[k] = pv
    for key in ("rows", "kpis", "series", "views", "charts", "groups"):
        if key in node and not out.get(key):
            return _GONE
    if "layout" in node:
        out["layout"] = [r for r in (out.get("layout") or []) if r]
        if not out["layout"]:
            return _GONE
    if "cards" in node and isinstance(node["cards"], list):
        out["cards"] = out.get("cards") or []
    return out


class _Gone:
    pass


_GONE = _Gone()



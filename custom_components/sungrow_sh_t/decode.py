"""Decode Modbus registers exactly as Home Assistant's YAML `modbus:` does.

A faithful port of Home Assistant 2026.10.2
`homeassistant/components/modbus/entity.py` (`ModbusStructEntity`:
`_swap_registers`, `__process_raw_value`, `unpack_structure_result`) and
`validators.py` (`struct_validator`, `DEFAULT_STRUCT_FORMAT`), Apache-2.0,
(c) the Home Assistant authors. Ported so every raw entity this integration
publishes is the same string the YAML produced, character for character: the
387 template sensors read these strings.

Pure Python, no Home Assistant import, so it is tested on its own. `encode()`
is the inverse, used only by the simulator and the tests.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

#: data_type -> (struct id, register count). HA's DEFAULT_STRUCT_FORMAT.
_FORMATS: dict[str, tuple[str, int]] = {
    "int16": ("h", 1),
    "uint16": ("H", 1),
    "float16": ("e", 1),
    "int32": ("i", 2),
    "uint32": ("I", 2),
    "float32": ("f", 2),
    "int64": ("q", 4),
    "uint64": ("Q", 4),
    "float64": ("d", 4),
    "string": ("s", 0),
    "custom": ("?", 0),
}
_INT_TYPES = {"int16", "int32", "int64", "uint16", "uint32", "uint64"}


@dataclass(frozen=True)
class Spec:
    """One Modbus read, as the YAML declares it, resolved the way HA resolves it."""

    data_type: str
    count: int
    structure: str
    swap: str | None
    scale: float
    offset: float
    precision: int
    slave_count: int = 0
    min_value: float | None = None
    max_value: float | None = None
    zero_suppress: float | None = None
    nan_value: int | None = None

    @classmethod
    def from_entry(cls, e: dict[str, Any]) -> Spec:
        """HA's struct_validator plus ModbusStructEntity.__init__ defaults."""
        data_type = e.get("data_type", "int16")
        if data_type == "int":
            data_type = "int16"
        if data_type not in _FORMATS:
            raise ValueError(f"{e.get('name')}: data_type {data_type!r} not supported")
        struct_id, reg_count = _FORMATS[data_type]
        slave_count = int(e.get("slave_count") or e.get("virtual_count") or 0)
        if data_type == "custom":
            structure = e["structure"]
            count = int(e["count"])
            if struct.calcsize(structure) != count * 2:
                raise ValueError(
                    f"{e.get('name')}: structure {structure!r} is "
                    f"{struct.calcsize(structure)} bytes, count {count} is {count * 2}"
                )
        else:
            count = int(e["count"]) if data_type == "string" else reg_count
            if slave_count:
                structure = f">{slave_count + 1}{struct_id}"
            elif data_type == "string":
                structure = f">{count * 2}s"
            else:
                structure = f">{struct_id}"
        precision = e.get("precision")
        if precision is None:
            precision = 0 if data_type in _INT_TYPES else 2
        return cls(
            data_type=data_type,
            count=count,
            structure=structure,
            swap=e.get("swap"),
            scale=float(e.get("scale", 1.0)),
            offset=float(e.get("offset", 0)),
            precision=int(precision),
            slave_count=slave_count,
            min_value=e.get("min_value"),
            max_value=e.get("max_value"),
            zero_suppress=e.get("zero_suppress"),
            nan_value=e.get("nan_value"),
        )

    @property
    def registers(self) -> int:
        """Registers read per poll (HA reads count * (slave_count + 1))."""
        return self.count * (self.slave_count + 1)


def _swap(spec: Spec, registers: list[int], slave_count: int) -> list[int]:
    if slave_count:
        out: list[int] = []
        for i in range(spec.slave_count + 1):
            inx = i * spec.count
            out.extend(_swap(spec, registers[inx : inx + spec.count], 0))
        return out
    regs = list(registers)
    if spec.swap in ("byte", "word_byte"):
        regs = [int.from_bytes(r.to_bytes(2, "little"), "big") for r in regs]
    if spec.swap in ("word", "word_byte"):
        regs.reverse()
    return regs


def _process(spec: Spec, entry: Any) -> str | None:
    if spec.nan_value is not None and entry in (spec.nan_value, -spec.nan_value):
        return None
    if isinstance(entry, bytes):
        return entry.decode()
    if entry != entry:  # NaN
        return None
    val: float | int = spec.scale * entry + spec.offset
    if spec.min_value is not None and val < spec.min_value:
        val = spec.min_value
    if spec.max_value is not None and val > spec.max_value:
        val = spec.max_value
    if spec.zero_suppress is not None and abs(val) <= spec.zero_suppress:
        return "0"
    if spec.precision == 0:
        return str(round(val))
    return f"{float(val):.{spec.precision}f}"


def decode(spec: Spec, registers: list[int]) -> str | None:
    """The state string HA's YAML modbus sensor would publish."""
    regs = _swap(spec, registers, spec.slave_count) if spec.swap else list(registers)
    raw = b"".join(r.to_bytes(2, "big") for r in regs)
    if spec.data_type == "string":
        return raw.decode()
    if raw == b"nan\x00":
        return None
    try:
        values = struct.unpack(spec.structure, raw)
    except struct.error:
        return None
    if len(values) > 1:
        parts = []
        for v in values:
            t = _process(spec, v)
            parts.append(str(t) if spec.data_type != "custom" else (str(t) if t is not None else "0"))
        return ",".join(parts)
    return _process(spec, values[0])


def encode(spec: Spec, state: str) -> list[int] | None:
    """Registers that decode back to `state`, or None if none can be found.

    The simulator's seeding only: scale is inverted and rounded to an integer
    raw value; callers check `decode(spec, encode(spec, s)) == s`.
    """
    if spec.data_type == "string":
        raw = state.encode()[: spec.count * 2].ljust(spec.count * 2, b"\x00")
        return [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]
    parts = state.split(",")
    fmt = spec.structure
    codes = _codes(fmt)
    if len(codes) != len(parts):
        return None
    values: list[Any] = []
    for code, p in zip(codes, parts, strict=True):
        if code in "sp":
            # a text field inside a custom structure: struct.pack pads or cuts
            # it to the declared length, exactly as it was unpacked
            values.append(p.encode())
            continue
        try:
            x = (float(p) - spec.offset) / spec.scale
        except ValueError:
            return None
        values.append(x if code in "efd" else int(round(x)))
    try:
        raw = struct.pack(fmt, *values)
    except struct.error:
        return None
    regs = [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]
    if spec.swap:
        # every swap HA does is its own inverse
        regs = _swap(spec, regs, spec.slave_count)
    return regs


def _codes(fmt: str) -> list[str]:
    """The value-producing format codes of a struct format, repeats expanded."""
    out: list[str] = []
    num = ""
    for ch in fmt.lstrip("@=<>!"):
        if ch.isdigit():
            num += ch
            continue
        n = int(num) if num else 1
        num = ""
        if ch in "xX":
            continue
        if ch in "sp":
            out.append(ch)
        else:
            out.extend([ch] * n)
    return out
